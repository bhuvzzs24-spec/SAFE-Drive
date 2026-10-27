# SAFE-Drive repository audit

**Audited:** 27 October 2026
**Repository root:** `safe_drive_research/`
**Branch:** `main`
**Remote:** `https://github.com/bhuvzzs24-spec/SAFE-Drive.git`
**HEAD at audit:** `daf9f60`
**Working tree at audit:** clean

## Architecture found

- **Frontend:** Jinja-rendered HTML with plain JavaScript and CSS. No React/Vue build system or frontend package manager is present. Styles live in `static/app.css`; behavior is in `static/app.js`.
- **Backend:** Flask in `app.py`. Routes cover upload, RTSP session creation, status, stop, processed video, and JSONL events. One in-process worker handles jobs serially; the job registry is memory-only.
- **Input:** Uploaded video and manually entered/configured RTSP/RTSPS work in the current pipeline. `camera_input.py` parses demo, video, webcam and RTSP settings, but webcam capture is not wired. Missing config is represented as demo/upload mode.
- **Detection/tracking:** Ultralytics YOLO with default `yolov8n.pt` and DeepSORT. COCO vehicle classes are filtered. Weights are not committed; there are no custom helmet weights. Track trails, per-track result summaries and expiration reporting are incomplete.
- **Speed/calibration:** Homography-based road-plane mapping and a timestamp-aware estimator exist. The current video runner requires calibration rather than continuing detection with speed unavailable. Lane-specific rules, tolerance, temporal speed confirmation and measured quality reporting are incomplete.
- **Events/risk:** Pairwise closest-approach/TTC screening, advisory scoring and JSONL event output exist. There is no durable deduplication policy for all event types or review workflow.
- **Database:** No SQL database is configured. Events are JSONL files; uploaded clips and outputs are files in ignored `local_data/`. There is no relational schema or database persistence to preserve.
- **Helmet:** No helmet model, supported helmet classes, rider-to-helmet association, training script or validation script exists.
- **Tests:** Five `unittest` cases cover camera-source config normalization only. No CV, speed, event, API or persistence tests existed.
- **Dependencies:** `pyproject.toml` makes Flask an optional `web` extra, although `app.py` imports it unconditionally. The inspected system Python has OpenCV and Ultralytics but no Flask, so the web app cannot start with that interpreter until web dependencies are installed.

## Styling failure diagnosis

The dashboard stylesheet is present and the Jinja template links it with Flask's `url_for('static', filename='app.css')`. In the earlier browser state, the user opened `templates/index.html` through a `file://` URL. A raw file view does not execute Jinja, so the stylesheet URL remains a literal template expression and the page appears unstyled. Serve the template through Flask at `http://127.0.0.1:5170/`; do not open the template file directly. The optional Flask dependency also needs to be installed for that route to exist.

## Verified repository state

At the audit point, the current branch was `main`, `origin` matched the repository URL above, the newest commit was `daf9f60`, and no user changes were present in the working tree. No model weights, datasets, CCTV credentials or generated result files were tracked.

## Prioritized work

1. Make the documented web app dependency install by default and clearly direct users to the Flask URL, fixing the common raw-template/un-styled failure.
2. Keep detection/tracking alive when calibration is absent; expose speed as unavailable instead of blocking analysis.
3. Produce actual per-track summaries, confidence/class labels and trajectory trails, with expiration and counts.
4. Add configurable, time-confirmed speed rules and event deduplication.
5. Persist sessions, tracks, events and review decisions in SQLite; keep evidence files separate.
6. Add real webcam capture and improve RTSP lifecycle/health reporting.
7. Add optional custom helmet inference/training/validation and rider association only when a compatible dataset/model exists.
8. Expand tests incrementally and distinguish code-level checks from tests that need real cameras, data or trained weights.

The audit found no existing database, frontend framework, helmet model or user changes to overwrite. Continue incrementally from the current history.
