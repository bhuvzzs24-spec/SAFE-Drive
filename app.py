"""Local SAFE-Drive review dashboard. Run with: python app.py"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hmac
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import uuid

from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from safe_drive.camera_input import CameraConfigurationError, load_camera_source
from safe_drive.rules import SpeedLimitRule
from safe_drive.storage import SQLiteStore
from safe_drive.job_runner import supervise_job
from safe_drive.security import (RateGate, confined_file, deployment_settings,
                                 registered_camera_url, validate_video_header)

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SAFE_DRIVE_DATA", ROOT / "local_data")).resolve()
ALLOWED_VIDEO = {"mp4", "mov", "mkv", "avi", "webm"}
JOB_ID = re.compile(r"^[a-f0-9]{32}$")
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
WORKERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="safe-drive")
CAMERA_CONFIG = Path(os.environ.get("SAFE_DRIVE_CAMERA_CONFIG", ROOT / "config/camera.json"))
STORE = SQLiteStore(os.environ.get("SAFE_DRIVE_DATABASE", DATA / "safe_drive.sqlite3"))


def create_app(test_config=None) -> Flask:
    app = Flask(__name__)
    app.config.update(deployment_settings())
    if test_config:
        app.config.update(test_config)
    if app.config["DEMO_PRODUCTION"]:
        app.config["SESSION_COOKIE_SECURE"] = True
    app.secret_key = app.config["SECRET_KEY"] or secrets.token_hex(32)
    if os.environ.get("SAFE_DRIVE_TRUST_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app,x_proto=1)
    login_gate = RateGate()
    job_slots = threading.BoundedSemaphore(2)
    DATA.mkdir(parents=True, exist_ok=True)
    STORE.recover_interrupted_sessions()
    app.logger.setLevel(logging.INFO)

    @app.before_request
    def authorize_request():
        production = app.config["DEMO_PRODUCTION"]
        allowed_hosts = app.config["DEMO_HOSTS"] if production else {"127.0.0.1","localhost"}
        if request.host.split(":", 1)[0].lower() not in allowed_hosts:
            abort(403)
        trusted_local = not production and request.remote_addr in {"127.0.0.1","::1"}
        user = app.config["DEMO_USERS"].get(session.get("user"))
        if user and not hmac.compare_digest(session.get("auth_fingerprint",""),hashlib.sha256(user["password_hash"].encode()).hexdigest()):
            user = None
        g.role = "admin" if trusted_local else user["role"] if user else "public"
        g.username = session.get("user") if user else None
        private = request.endpoint not in {"home","static","health","login","demo_info","demo_video","get_sessions","get_analytics"}
        if private and g.role == "public":
            return jsonify(error="Sign in is required for private analysis and evidence."),401
        if production and request.method == "POST" and not request.is_secure:
            return jsonify(error="HTTPS is required."),403
        if request.endpoint in {"create_job","stop_job"} and g.role not in {"admin","analyst"}:
            abort(403)
        if request.endpoint == "create_job" and not app.config["DEMO_ALLOW_UPLOADS"]:
            return jsonify(error="Uploads are disabled for this controlled demo."),403
        if request.endpoint == "create_camera_job" and (g.role != "admin" or production or not app.config["DEMO_CAMERAS"]):
            return jsonify(error="Live cameras are disabled on the public demo. Use a separately secured private operator instance."),403
        if request.endpoint == "review_event" and g.role not in {"admin","reviewer"}:
            abort(403)
        if request.method == "POST" and request.endpoint != "static":
            submitted = request.headers.get("X-CSRF-Token", "") or (request.form.get("csrf_token", "") if request.endpoint in {"login","logout"} else "")
            expected = session.get("csrf_token", "")
            if not expected or not hmac.compare_digest(submitted, expected):
                abort(403)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; media-src 'self' blob:; img-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if app.config["DEMO_PRODUCTION"] and request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    @app.route("/login",methods=["GET","POST"])
    def login():
        session.setdefault("csrf_token",secrets.token_urlsafe(32))
        error = None
        if request.method == "POST":
            if not login_gate.allow():
                return render_template("login.html",csrf_token=session["csrf_token"],error="Too many sign-in attempts. Wait one minute."),429
            name,password = request.form.get("username",""),request.form.get("password","")
            user = app.config["DEMO_USERS"].get(name)
            # Equal-cost password hashing even for unknown users.
            fallback = app.config.get("DEMO_DUMMY_HASH")
            if fallback is None:
                from werkzeug.security import generate_password_hash
                fallback = app.config["DEMO_DUMMY_HASH"] = generate_password_hash(secrets.token_urlsafe(32))
            valid = check_password_hash(user["password_hash"] if user else fallback,password[:1024])
            if user and valid and len(password) <= 1024:
                session.clear()
                session.update(user=name,csrf_token=secrets.token_urlsafe(32),
                               auth_fingerprint=hashlib.sha256(user["password_hash"].encode()).hexdigest())
                session.permanent = True
                return redirect(url_for("home"))
            error = "Invalid username or password."
        return render_template("login.html",csrf_token=session["csrf_token"],error=error),401 if error else 200

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    def public_empty_analytics():
        return {"sessions":0,"completed_sessions":0,"frames_processed":0,"vehicle_tracks":0,
                "tracks_with_valid_speed":0,"pedestrians":0,"events":0,"pending_events":0,"reviewed_events":0,"activity":[]}

    def sample_file():
        source = app.config["DEMO_SAMPLE_VIDEO"]
        if not source or not app.config["DEMO_SAMPLE_LICENSE"]:
            abort(404)
        target = Path(source).expanduser()
        if target.is_symlink() or not target.is_file() or target.stat().st_size > app.config["MAX_CONTENT_LENGTH"]:
            abort(404)
        validate_video_header(target,target.suffix.lstrip(".").lower())
        return target.resolve()

    @app.get("/api/demo")
    def demo_info():
        available = False
        try:
            sample_file()
            available = True
        except (HTTPException,ValueError,OSError):
            pass
        return jsonify(mode="public_sample",available=available,inference=False,
                       license=app.config["DEMO_SAMPLE_LICENSE"] if available else None,
                       video_url="/api/demo/video" if available else None)

    @app.get("/api/demo/video")
    def demo_video():
        return send_file(sample_file(),conditional=True)

    @app.get("/")
    def home():
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        try:
            default_source = load_camera_source(CAMERA_CONFIG)
            camera_status = default_source.status_label
            camera_id = default_source.camera_id
        except CameraConfigurationError:
            camera_status, camera_id = "CAMERA CONFIG INVALID", ""
        if app.config["DEMO_PRODUCTION"]:
            camera_status,camera_id = "LIVE CAMERAS DISABLED",""
        if g.role == "public":
            camera_status,camera_id = "PUBLIC SAMPLE MODE",""
        return render_template("index.html", csrf_token=session["csrf_token"],
                               model=Path(os.environ.get("SAFE_DRIVE_MODEL", "yolov8n.pt")).name if app.config["DEMO_PRODUCTION"] else os.environ.get("SAFE_DRIVE_MODEL", "yolov8n.pt"),
                               role=g.role,public_demo=app.config["DEMO_PRODUCTION"],
                               can_upload=g.role in {"admin","analyst"} and app.config["DEMO_ALLOW_UPLOADS"],
                               can_camera=g.role == "admin" and app.config["DEMO_CAMERAS"],
                               can_review=g.role in {"admin","reviewer"},
                               camera_status=camera_status, camera_id=camera_id,
                               database_label=STORE.path.name if g.role != "public" else "Private storage",
                               helmet_model_available=Path(os.environ.get("SAFE_DRIVE_HELMET_MODEL", "")).expanduser().is_file())

    def job_or_404(job_id: str) -> dict:
        if not JOB_ID.fullmatch(job_id):
            abort(404)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            abort(404)
        return job

    def analyze(job_id: str, source: Path | str, calibration_path: Path | None, model: str,
                stop_event: threading.Event, duration_s: int | None, source_label: str,
                speed_rule: SpeedLimitRule) -> None:
        folder = DATA / job_id
        output_video = folder / "annotated.mp4"
        events_path = folder / "events.jsonl"
        try:
            if stop_event.is_set():
                with JOBS_LOCK:
                    JOBS[job_id]["status"] = "cancelled"
                STORE.update_session(job_id, "cancelled")
                return
            with JOBS_LOCK:
                JOBS[job_id].update(status="running",output=str(output_video),events=str(events_path))
            STORE.update_session(job_id,"running")
            result = supervise_job(job_id,source,calibration_path,model,folder,STORE.path,stop_event,
                                   duration_s,source_label,speed_rule,app.config["DEMO_MAX_JOB_SECONDS"],
                                   lambda frames,elapsed,tracks:update_progress(job_id,frames,elapsed,tracks))
            STORE.save_tracks(job_id, result["tracks"])
            STORE.update_session(job_id, "completed", result["frames_processed"],
                                 {k: v for k, v in result.items() if k != "tracks"},
                                 calibration_status=result["calibration_status"])
            with JOBS_LOCK:
                warning = "Camera stream ended before the requested duration." if result["source_ended"] else None
                JOBS[job_id].update(status="completed", output=str(output_video), events=str(events_path),
                                    frames_processed=result["frames_processed"], warning=warning,
                                    tracks=result["tracks"],
                                    calibration_status=result["calibration_status"],
                                    calibration_message=result["calibration_message"])
        except (Exception, SystemExit) as exc:  # includes clear errors from missing optional modules
            if isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://")):
                # Avoid writing camera credentials embedded in a URL to logs or the UI.
                app.logger.warning("Live camera analysis failed for job %s; details redacted", job_id)
                message = "Camera analysis failed. Check the RTSP address, network, credentials, and stream codec."
            else:
                app.logger.warning("Analysis failed job=%s category=%s",job_id,type(exc).__name__)
                message = "Analysis failed or exceeded its processing deadline. Check the video, configured weights and calibration."
            with JOBS_LOCK:
                JOBS[job_id].update(status="failed", error=message)
            try:
                STORE.update_session(job_id, "failed", error_message=message)
            except Exception:
                app.logger.error("Could not persist failure job=%s",job_id)
        finally:
            job_slots.release()
            with JOBS_LOCK:
                finished = [key for key,value in JOBS.items() if value["status"] in {"completed","failed","cancelled"}]
                for key in finished[:-100]:
                    JOBS.pop(key,None)

    def update_progress(job_id: str, frames: int, elapsed: float, tracks: dict) -> None:
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id].update(frames_processed=frames, elapsed_s=elapsed, tracks=tracks)
        STORE.save_tracks(job_id, tracks)
        STORE.update_session(job_id, "running", frames, tracks)

    def save_optional_calibration(upload, folder: Path) -> tuple[Path | None, str]:
        if not upload or not upload.filename:
            return None, "missing"
        try:
            from safe_drive.geometry import RoadPlane

            raw = upload.stream.read(65537)
            if len(raw) > 65536:
                return None,"invalid"
            calibration = json.loads(raw)
            if len(calibration["image_points_px"]) > 256:
                return None,"invalid"
            plane = RoadPlane(calibration["image_points_px"], calibration["road_points_m"])
            plane.transform(plane.image_points)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None, "invalid"
        path = folder / "calibration.json"
        path.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
        return path, "configured"

    def parse_speed_rule(form) -> SpeedLimitRule:
        raw_limit = form.get("speed_limit_kmh", "").strip()
        limit = float(raw_limit) if raw_limit else None
        tolerance = float(form.get("speed_tolerance_kmh", "0") or 0)
        confirmation = float(form.get("speed_confirmation_s", "1") or 1)
        return SpeedLimitRule(limit, tolerance, confirmation)

    def configured_model():
        supplied = request.form.get("model", "").strip()
        configured = os.environ.get("SAFE_DRIVE_MODEL", "yolov8n.pt")
        if app.config["DEMO_PRODUCTION"]:
            if supplied and supplied not in {configured,Path(configured).name}:
                raise ValueError("Use the server-configured detector model.")
            return configured
        return supplied or configured

    def reserve_job():
        used = sum(path.stat().st_size for path in DATA.rglob("*") if path.is_file() and not path.is_symlink())
        if shutil.disk_usage(DATA).free < app.config["DEMO_MIN_FREE_BYTES"] or used >= app.config["DEMO_MAX_DATA_BYTES"]:
            abort(507)
        if not job_slots.acquire(blocking=False):
            abort(429)
        g.job_reserved = True

    def release_reservation():
        if getattr(g,"job_reserved",False):
            job_slots.release()
            g.job_reserved = False

    @app.teardown_request
    def cleanup_unsubmitted_job(_error):
        if getattr(g,"job_reserved",False) and not getattr(g,"job_submitted",False):
            release_reservation()
            folder = getattr(g,"job_folder",None)
            if folder is not None:
                shutil.rmtree(folder,ignore_errors=True)

    def queue_job(job_id,folder,source,calibration_path,model,stop_event,duration_s,label,speed_rule):
        try:
            WORKERS.submit(analyze,job_id,source,calibration_path,model,stop_event,duration_s,label,speed_rule)
            g.job_submitted = True
        except Exception:
            release_reservation()
            STORE.update_session(job_id,"failed",error_message="Worker could not accept this analysis.")
            shutil.rmtree(folder)
            raise

    @app.post("/api/jobs")
    def create_job():
        upload = request.files.get("video")
        calibration_upload = request.files.get("calibration")
        if not upload or not upload.filename:
            return jsonify(error="Choose a traffic video file."), 400
        safe_name = secure_filename(upload.filename)
        extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if extension not in ALLOWED_VIDEO:
            return jsonify(error=f"Unsupported video type. Use: {', '.join(sorted(ALLOWED_VIDEO))}."), 400
        # Calibration is optional: detector/tracker output remains useful for
        # counts and trajectories, while metric speed is explicitly unavailable.
        try:
            model = configured_model()
        except ValueError as exc:
            return jsonify(error=str(exc)),400
        if not model or len(model) > 240:
            return jsonify(error="Enter a valid model filename or local model path."), 400
        try:
            speed_rule = parse_speed_rule(request.form)
        except (ValueError, TypeError) as exc:
            return jsonify(error=f"Speed rule is invalid: {exc}"), 400
        reserve_job()
        job_id = uuid.uuid4().hex
        folder = DATA / job_id
        folder.mkdir(parents=True, exist_ok=False,mode=0o700)
        g.job_folder = folder
        video_path = folder / f"input.{extension}"
        calibration_path, calibration_status = save_optional_calibration(calibration_upload, folder)
        upload.save(video_path)
        try:
            validate_video_header(video_path,extension)
        except ValueError as exc:
            release_reservation()
            shutil.rmtree(folder)
            return jsonify(error=str(exc)),400
        stop_event = threading.Event()
        camera_id = "uploaded-video"
        if calibration_path:
            try:
                camera_id = json.loads(calibration_path.read_text(encoding="utf-8")).get("camera_id") or camera_id
            except (OSError, json.JSONDecodeError):
                pass
        STORE.create_session(job_id, str(camera_id), "uploaded_video", safe_name, model, calibration_status)
        with JOBS_LOCK:
            JOBS[job_id] = {"id": job_id, "name": safe_name, "status": "queued", "model": model,
                            "source_mode": "uploaded_video",
                            "calibration_status": calibration_status,
                            "speed_limit_kmh": speed_rule.limit_kmh,
                            "stop_event": stop_event}
        queue_job(job_id,folder,video_path,calibration_path,model,stop_event,None,safe_name,speed_rule)
        return jsonify(id=job_id, status="queued"), 202

    @app.post("/api/camera-jobs")
    def create_camera_job():
        if request.form.get("stream_url", "").strip():
            return jsonify(error="Client-supplied camera URLs are disabled. Use the server-registered source."),400
        try:
            configured_source = load_camera_source(CAMERA_CONFIG)
            registered_camera_url(str(configured_source.source),os.environ.get("SAFE_DRIVE_CAMERA_ALLOWED_IPS", ""))
        except (CameraConfigurationError,ValueError):
            return jsonify(error="The server camera is not authorized or configured correctly."),400
        if configured_source.mode != "rtsp" or not configured_source.source:
            return jsonify(error="No RTSP camera is configured. Enter a stream URL or configure SAFE_DRIVE_CAMERA_URL."), 400
        if len(str(configured_source.source)) > 2048:
            return jsonify(error="Camera stream URL is too long."), 400
        stream_url = str(configured_source.source)
        calibration_upload = request.files.get("calibration")
        try:
            duration_s = int(request.form.get("duration_s", "300"))
        except ValueError:
            return jsonify(error="Duration must be a whole number of seconds."), 400
        if not 10 <= duration_s <= 3600:
            return jsonify(error="Choose a live analysis duration between 10 and 3600 seconds."), 400
        model = configured_model()
        if not model or len(model) > 240:
            return jsonify(error="Enter a valid model filename or local model path."), 400
        try:
            speed_rule = parse_speed_rule(request.form)
        except (ValueError, TypeError) as exc:
            return jsonify(error=f"Speed rule is invalid: {exc}"), 400
        reserve_job()
        job_id = uuid.uuid4().hex
        folder = DATA / job_id
        folder.mkdir(parents=True, exist_ok=False,mode=0o700)
        g.job_folder = folder
        calibration_path, calibration_status = save_optional_calibration(calibration_upload, folder)
        calibration = {}
        if calibration_path:
            try:
                calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        stop_event = threading.Event()
        camera_label = str(calibration.get("camera_id") or configured_source.camera_id)[:80]
        STORE.create_session(job_id, camera_label, "rtsp", camera_label, model, calibration_status)
        with JOBS_LOCK:
            JOBS[job_id] = {"id": job_id, "name": camera_label, "status": "queued", "model": model,
                            "source_mode": "rtsp", "stop_event": stop_event, "live": True,
                            "calibration_status": calibration_status,
                            "speed_limit_kmh": speed_rule.limit_kmh}
        queue_job(job_id,folder,stream_url,calibration_path,model,stop_event,duration_s,camera_label,speed_rule)
        return jsonify(id=job_id, status="queued"), 202

    @app.get("/api/jobs/<job_id>")
    def get_job(job_id: str):
        job = dict(job_or_404(job_id))
        job.pop("output", None)
        job.pop("events", None)
        job.pop("stop_event", None)
        return jsonify(job)

    @app.post("/api/jobs/<job_id>/stop")
    def stop_job(job_id: str):
        job = job_or_404(job_id)
        with JOBS_LOCK:
            if job["status"] not in {"queued", "running"}:
                return jsonify(status=job["status"]), 409
            job["status"] = "stopping"
            job["stop_event"].set()
        return jsonify(status="stopping"), 202

    @app.get("/api/jobs/<job_id>/video")
    def get_video(job_id: str):
        job = job_or_404(job_id)
        if job["status"] != "completed":
            abort(404)
        return send_file(confined_file(DATA,job["output"]), mimetype="video/mp4", conditional=True)

    @app.get("/api/jobs/<job_id>/events")
    def get_events(job_id: str):
        job = job_or_404(job_id)
        if job["status"] == "failed":
            return jsonify(events=[], error=job.get("error")), 200
        if job["status"] not in {"running", "stopping", "completed"} or "events" not in job:
            return jsonify(events=[]), 200
        persisted = STORE.list_events(job_id)
        if persisted:
            return jsonify(events=persisted)
        events_file = Path(job["events"])
        events = []
        if events_file.exists():
            for line in events_file.read_text(encoding="utf-8").splitlines()[-500:]:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return jsonify(events=events)

    @app.get("/api/sessions")
    def get_sessions():
        return jsonify(sessions=STORE.list_sessions() if g.role != "public" else [])

    @app.get("/api/analytics")
    def get_analytics():
        return jsonify(STORE.analytics() if g.role != "public" else public_empty_analytics())

    def session_or_404(session_id: str) -> dict:
        if not JOB_ID.fullmatch(session_id):
            abort(404)
        record = STORE.get_session(session_id)
        if not record:
            abort(404)
        return record

    @app.get("/api/sessions/<session_id>/events")
    def get_session_events(session_id: str):
        session_or_404(session_id)
        return jsonify(events=STORE.list_events(session_id))

    @app.get("/api/sessions/<session_id>/tracks")
    def get_session_tracks(session_id: str):
        session_or_404(session_id)
        return jsonify(tracks=STORE.list_tracks(session_id))

    @app.get("/api/sessions/<session_id>/video")
    def get_session_video(session_id: str):
        record = session_or_404(session_id)
        if record["status"] != "completed":
            abort(404)
        target = DATA / session_id / "annotated.mp4"
        if not target.is_file():
            abort(404)
        return send_file(confined_file(DATA,target), mimetype="video/mp4", conditional=True)

    @app.get("/api/sessions/<session_id>/original")
    def get_session_original(session_id: str):
        record = session_or_404(session_id)
        if record["source_mode"] != "uploaded_video":
            abort(404)
        folder = DATA / session_id
        matches = [p for p in folder.glob("input.*") if p.is_file()]
        if not matches:
            abort(404)
        return send_file(confined_file(DATA,matches[0]), conditional=True)

    @app.post("/api/events/<event_id>/review")
    def review_event(event_id: str):
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload,dict) or not isinstance(payload.get("reviewer",""),str) or not isinstance(payload.get("decision",""),str):
            return jsonify(error="Review must contain a JSON object with text fields."),400
        try:
            STORE.review_event(event_id, payload.get("decision", ""), g.username or payload.get("reviewer", ""))
        except KeyError:
            return jsonify(error="Event not found."), 404
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(event_id=event_id, review_status=payload["decision"]), 200

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error="Upload exceeds the configured size limit."), 413

    @app.errorhandler(HTTPException)
    def request_error(error):
        return jsonify(error=error.name),error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.error("Request failed category=%s",type(error).__name__)
        return jsonify(error="Request could not be completed."),500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT",os.environ.get("SAFE_DRIVE_PORT", "5170"))), debug=False)
