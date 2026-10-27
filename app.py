"""Local SAFE-Drive review dashboard. Run with: python app.py"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import threading
import uuid

from flask import Flask, abort, jsonify, render_template, request, send_file, session
from werkzeug.utils import secure_filename

from safe_drive.cli import run_video
from safe_drive.camera_input import CameraConfigurationError, load_camera_source, resolve_camera_source
from safe_drive.rules import SpeedLimitRule
from safe_drive.storage import SQLiteStore

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SAFE_DRIVE_DATA", ROOT / "local_data")).resolve()
ALLOWED_VIDEO = {"mp4", "mov", "mkv", "avi", "webm"}
JOB_ID = re.compile(r"^[a-f0-9]{32}$")
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
WORKERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="safe-drive")
CAMERA_CONFIG = Path(os.environ.get("SAFE_DRIVE_CAMERA_CONFIG", ROOT / "config/camera.json"))
STORE = SQLiteStore(os.environ.get("SAFE_DRIVE_DATABASE", DATA / "safe_drive.sqlite3"))


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("SAFE_DRIVE_SECRET") or secrets.token_hex(32)
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("SAFE_DRIVE_MAX_UPLOAD", 300 * 1024 * 1024))
    DATA.mkdir(parents=True, exist_ok=True)
    app.logger.setLevel(logging.INFO)

    @app.before_request
    def local_host_only():
        # This application is intended for localhost only, never as a public service.
        if request.host.split(":", 1)[0] not in {"127.0.0.1", "localhost"}:
            abort(403)
        if request.method == "POST" and request.endpoint != "static":
            submitted = request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf_token", "")
            if not expected or not hmac.compare_digest(submitted, expected):
                abort(403)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; media-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def home():
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        try:
            default_source = load_camera_source(CAMERA_CONFIG)
            camera_status = default_source.status_label
            camera_id = default_source.camera_id
        except CameraConfigurationError:
            camera_status, camera_id = "CAMERA CONFIG INVALID", ""
        return render_template("index.html", csrf_token=session["csrf_token"],
                               model=os.environ.get("SAFE_DRIVE_MODEL", "yolov8n.pt"),
                               camera_status=camera_status, camera_id=camera_id,
                               database_label=STORE.path.name,
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
        with JOBS_LOCK:
            if stop_event.is_set():
                JOBS[job_id]["status"] = "cancelled"
                STORE.update_session(job_id, "cancelled")
                return
            JOBS[job_id].update(status="running", output=str(DATA / job_id / "annotated.mp4"),
                                events=str(DATA / job_id / "events.jsonl"))
        STORE.update_session(job_id, "running")
        folder = DATA / job_id
        output_video = folder / "annotated.mp4"
        events_path = folder / "events.jsonl"
        try:
            result = run_video(source, calibration_path, model, output_video, events_path,
                               0.35, stop_event, duration_s, source_label,
                               lambda frames, elapsed, tracks: update_progress(job_id, frames, elapsed, tracks),
                               speed_rule,
                               lambda event: STORE.insert_event(job_id, event))
            with JOBS_LOCK:
                warning = "Camera stream ended before the requested duration." if result["source_ended"] else None
                JOBS[job_id].update(status="completed", output=str(output_video), events=str(events_path),
                                    frames_processed=result["frames_processed"], warning=warning,
                                    tracks=result["tracks"],
                                    calibration_status=result["calibration_status"],
                                    calibration_message=result["calibration_message"])
            STORE.save_tracks(job_id, result["tracks"])
            STORE.update_session(job_id, "completed", result["frames_processed"],
                                 {k: v for k, v in result.items() if k != "tracks"},
                                 calibration_status=result["calibration_status"])
        except (Exception, SystemExit) as exc:  # includes clear errors from missing optional modules
            if isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://")):
                # Avoid writing camera credentials embedded in a URL to logs or the UI.
                app.logger.warning("Live camera analysis failed for job %s; details redacted", job_id)
                message = "Camera analysis failed. Check the RTSP address, network, credentials, and stream codec."
            else:
                app.logger.exception("Analysis job %s failed", job_id)
                message = f"{type(exc).__name__}: {exc}"
            with JOBS_LOCK:
                JOBS[job_id].update(status="failed", error=message)
            STORE.update_session(job_id, "failed", error_message=message)

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

            calibration = json.load(upload.stream)
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
        model = request.form.get("model", "yolov8n.pt").strip()
        if not model or len(model) > 240:
            return jsonify(error="Enter a valid model filename or local model path."), 400
        try:
            speed_rule = parse_speed_rule(request.form)
        except (ValueError, TypeError) as exc:
            return jsonify(error=f"Speed rule is invalid: {exc}"), 400
        job_id = uuid.uuid4().hex
        folder = DATA / job_id
        folder.mkdir(parents=True, exist_ok=False)
        video_path = folder / f"input.{extension}"
        calibration_path, calibration_status = save_optional_calibration(calibration_upload, folder)
        upload.save(video_path)
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
        WORKERS.submit(analyze, job_id, video_path, calibration_path, model, stop_event,
                       None, safe_name, speed_rule)
        return jsonify(id=job_id, status="queued"), 202

    @app.post("/api/camera-jobs")
    def create_camera_job():
        stream_url = request.form.get("stream_url", "").strip()
        if stream_url:
            try:
                configured_source = resolve_camera_source("rtsp", stream_url,
                                                          request.form.get("camera_id", "camera"))
            except CameraConfigurationError as exc:
                return jsonify(error=str(exc)), 400
        else:
            try:
                configured_source = load_camera_source(CAMERA_CONFIG)
            except CameraConfigurationError as exc:
                return jsonify(error=str(exc)), 400
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
        model = request.form.get("model", "yolov8n.pt").strip()
        if not model or len(model) > 240:
            return jsonify(error="Enter a valid model filename or local model path."), 400
        try:
            speed_rule = parse_speed_rule(request.form)
        except (ValueError, TypeError) as exc:
            return jsonify(error=f"Speed rule is invalid: {exc}"), 400
        job_id = uuid.uuid4().hex
        folder = DATA / job_id
        folder.mkdir(parents=True, exist_ok=False)
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
        WORKERS.submit(analyze, job_id, stream_url, calibration_path, model,
                       stop_event, duration_s, camera_label, speed_rule)
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
        return send_file(job["output"], mimetype="video/mp4", conditional=True)

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
        return jsonify(sessions=STORE.list_sessions())

    @app.get("/api/analytics")
    def get_analytics():
        return jsonify(STORE.analytics())

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
        return send_file(target, mimetype="video/mp4", conditional=True)

    @app.get("/api/sessions/<session_id>/original")
    def get_session_original(session_id: str):
        record = session_or_404(session_id)
        if record["source_mode"] != "uploaded_video":
            abort(404)
        folder = DATA / session_id
        matches = [p for p in folder.glob("input.*") if p.is_file()]
        if not matches:
            abort(404)
        return send_file(matches[0], conditional=True)

    @app.post("/api/events/<event_id>/review")
    def review_event(event_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            STORE.review_event(event_id, payload.get("decision", ""), payload.get("reviewer", ""))
        except KeyError:
            return jsonify(error="Event not found."), 404
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(event_id=event_id, review_status=payload["decision"]), 200

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error="Upload exceeds the configured size limit."), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("SAFE_DRIVE_PORT", "5170")), debug=False)
