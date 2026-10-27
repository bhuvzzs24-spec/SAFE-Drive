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
from safe_drive.geometry import RoadPlane

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SAFE_DRIVE_DATA", ROOT / "local_data")).resolve()
ALLOWED_VIDEO = {"mp4", "mov", "mkv", "avi", "webm"}
JOB_ID = re.compile(r"^[a-f0-9]{32}$")
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
WORKERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="safe-drive")


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
        return render_template("index.html", csrf_token=session["csrf_token"], model=os.environ.get("SAFE_DRIVE_MODEL", "yolov8n.pt"))

    def job_or_404(job_id: str) -> dict:
        if not JOB_ID.fullmatch(job_id):
            abort(404)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            abort(404)
        return job

    def analyze(job_id: str, video_path: Path, calibration_path: Path, model: str) -> None:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"
        folder = DATA / job_id
        output_video = folder / "annotated.mp4"
        events_path = folder / "events.jsonl"
        try:
            run_video(video_path, calibration_path, model, output_video, events_path, 50.0, 0.35)
            with JOBS_LOCK:
                JOBS[job_id].update(status="completed", output=str(output_video), events=str(events_path))
        except (Exception, SystemExit) as exc:  # includes clear errors from missing optional modules
            app.logger.exception("Analysis job %s failed", job_id)
            with JOBS_LOCK:
                JOBS[job_id].update(status="failed", error=f"{type(exc).__name__}: {exc}")

    @app.post("/api/jobs")
    def create_job():
        upload = request.files.get("video")
        calibration_upload = request.files.get("calibration")
        if not upload or not upload.filename or not calibration_upload or not calibration_upload.filename:
            return jsonify(error="Choose both a traffic video and a calibration JSON file."), 400
        safe_name = secure_filename(upload.filename)
        extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if extension not in ALLOWED_VIDEO:
            return jsonify(error=f"Unsupported video type. Use: {', '.join(sorted(ALLOWED_VIDEO))}."), 400
        try:
            calibration = json.load(calibration_upload.stream)
            RoadPlane(calibration["image_points_px"], calibration["road_points_m"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return jsonify(error=f"Calibration JSON is invalid: {exc}"), 400
        model = request.form.get("model", "yolov8n.pt").strip()
        if not model or len(model) > 240:
            return jsonify(error="Enter a valid model filename or local model path."), 400
        job_id = uuid.uuid4().hex
        folder = DATA / job_id
        folder.mkdir(parents=True, exist_ok=False)
        video_path = folder / f"input.{extension}"
        calibration_path = folder / "calibration.json"
        upload.save(video_path)
        calibration_path.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
        with JOBS_LOCK:
            JOBS[job_id] = {"id": job_id, "name": safe_name, "status": "queued", "model": model}
        WORKERS.submit(analyze, job_id, video_path, calibration_path, model)
        return jsonify(id=job_id, status="queued"), 202

    @app.get("/api/jobs/<job_id>")
    def get_job(job_id: str):
        job = dict(job_or_404(job_id))
        job.pop("output", None)
        job.pop("events", None)
        return jsonify(job)

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
        if job["status"] != "completed":
            return jsonify(events=[]), 200
        events_file = Path(job["events"])
        events = []
        if events_file.exists():
            for line in events_file.read_text(encoding="utf-8").splitlines()[-500:]:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return jsonify(events=events)

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error="Upload exceeds the configured size limit."), 413

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("SAFE_DRIVE_PORT", "5170")), debug=False)
