# Stage 1 — Repository audit

## Existing architecture

- **Backend:** Flask app in `app.py`, loopback-only, with upload, camera-job, status, stop, video and event routes. Jobs run in a single in-process background worker and job state is held in memory.
- **Frontend:** Jinja template plus plain JavaScript and CSS in `templates/` and `static/`; no frontend framework or WebSocket dependency.
- **Vision pipeline:** `src/safe_drive/cli.py` lazily loads Ultralytics YOLO and DeepSORT, then processes a video file or RTSP/RTSPS stream.
- **Analysis modules:** `geometry.py` maps road points with a homography; `speed.py` estimates timestamped metric speed; `encounters.py` screens pairwise closest approach; `risk.py` creates advisory scores; `events.py` appends JSONL.
- **Models:** no custom weights are bundled. The baseline defaults to `yolov8n.pt`, a general COCO model. There is no helmet model or helmet class policy in the current pipeline.
- **Persistence:** event records are JSONL files per job. There is no SQLite event history or reviewer workflow yet.
- **Legacy:** original student scripts are preserved in `legacy/` and documented as non-authoritative.

## Working features in the repository before this audit

- Offline video upload and annotated output.
- Manually entered, bounded RTSP/RTSPS sessions with stop control and event-list refresh.
- Vehicle class detection and DeepSORT track IDs.
- Calibrated road-plane projection, speed estimates, pairwise TTC/closest-approach screening, and JSONL review signals.
- Responsive dark dashboard and local project report.

The live-camera path still depends on the camera being reachable from the host, compatible OpenCV/FFmpeg support, valid calibration, and installed optional vision dependencies. It has no ONVIF discovery, reconnect strategy, or guaranteed real-time rate.

## Highest-priority gaps

1. No single typed camera-input/configuration layer; current dashboard URL is manual and webcam support is absent.
2. No explicit demo-mode state for “camera not configured.”
3. No trajectory trails or exposed per-track table with class, timestamps and confidence.
4. No trained helmet model, annotation recipe, training/validation scripts, temporal confirmation, or rider association.
5. No configurable road/lane speed thresholds or persistence-duration/tolerance policy.
6. No SQLite event store, durable review status, evidence-frame retention policy, or reviewer confirmation flow.
7. No tests existed before this stage.

## Stage 1 improvement delivered

Added `safe_drive.camera_input` to normalize demo, local-video, webcam-index and RTSP source settings; JSON configuration is overridden by environment variables. The dashboard reads the default config, labels the active source mode, and can use a configured RTSP URL when the form field is left blank. An absent camera config resolves to explicit demo/upload mode instead of a false connected-camera state. Added example configuration and unit tests for fallback, precedence, normalization, and invalid sources.

This is configuration plumbing only: webcam capture remains incomplete, and a configured source is not treated as connected until the capture worker opens it. Later stages should connect all typed sources to the capture worker.
