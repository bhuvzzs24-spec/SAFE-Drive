# SAFE-Drive Research Toolkit

For the prepared (not deployed) controlled public-demo configuration, security boundaries, operator accounts and host setup, see [Controlled demo deployment guide](docs/CONTROLLED_DEMO.md). Keep local research mode on loopback. Production defaults to a read-only sample view; private evidence requires authentication and live cameras are disabled.

SAFE-Drive is a research prototype for analyzing traffic video using calibrated vehicle trajectories and transparent encounter-risk signals. This repository is a cleaned, research-oriented continuation of the supplied student prototype. It is not a validated enforcement product and does not issue fines or identify people.

## What is implemented

- Road-plane homography from measured pixel-to-metre correspondences.
- Timestamp-based speed estimates with warm-up and calibration-quality states.
- Pairwise 2-D closest-approach/TTC screening using each track's positions and velocities.
- Configurable, explainable risk scoring with missing-signal reporting.
- Append-only JSONL event logging with content-addressed event identifiers.
- Local review dashboard for offline video and live camera analysis, annotated playback, and event review.
- Optional computer-vision and OCR dependencies, so analysis modules can be used without downloading model weights.

The starter code in `detector.py`, `main.py`, `near_miss.py`, `plate_reader.py`, `risk_engine.py`, and `speed_estimator.py` records the original prototype for comparison. `src/safe_drive/` contains the research modules. The original hard-coded pixel scale, horizontal-only TTC, plate-based automatic fine logic, and global near-miss attribution should not be used as scientific measurements.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
python -m pip install -e .                 # local dashboard and core analysis
python -m pip install -e '.[vision]'        # video detector/tracker pipeline
```

Video analysis requires an existing local Ultralytics **detection `.pt` checkpoint** supplied by you. Missing names such as `yolov8n.pt` fail explicitly; the runner does not download weights or auto-install model dependencies. Classification, pose, OBB, segmentation, YAML architectures and exported formats are outside the supported runner contract. Class names are read from the checkpoint rather than assuming COCO IDs. A general-object model does not detect helmet violations.

See [reproducible vision setup and evaluation](docs/VISION_INTEGRATION.md) for the exact interfaces, prerequisites, timestamp policy, artifact formats, synthetic checks, and real-inference evaluation procedure.

## Run one video

After creating a site-specific calibration file and installing the optional vision dependencies:

```bash
safe-drive video \
  --input path/to/traffic.mp4 \
  --model /absolute/path/to/licensed-detection-weights.pt \
  --calibration config/site-01.json \
  --output outputs/annotated.mp4 \
  --events outputs/events.jsonl
```

The runner writes annotated video, a per-frame `.tracks.jsonl`, a `.run.json` manifest, and screening events (including an empty JSONL on zero-event runs). Use new output paths for each run. It processes local video or RTSP/RTSPS input; add `--duration-sec 300` to bound a live session. Files use decoded presentation timestamps by default; repeated, reversed or missing timestamps fail. Use `--timestamp-mode cfr` only for independently verified constant-rate footage. Detector labels are mapped by name for supported cars, motorcycles, buses, trucks, and pedestrians; DeepSORT assigns session-local IDs to all of them. Pedestrians do not receive vehicle speed estimates or speed events. Calibration is optional: without valid measured calibration, detection/tracking continues and speed/TTC remain unavailable. A speed-limit event rule is disabled by default; set `--speed-limit-kmh`, `--speed-tolerance-kmh` and `--speed-confirmation-sec` to configure a rule. It does not read plates or issue fines. Review every event and validate calibration before interpreting km/h values.

## Local review dashboard

Install the `vision` extra, then run:

```bash
python app.py
```

Open `http://127.0.0.1:5170`. Choose **Video file** to upload a short clip. Optional live cameras require a separately secured local operator instance, explicit enablement and a server-registered IP-literal source on the allowed-IP list; request-supplied stream URLs are rejected. Live cameras are always disabled in public mode. See `docs/CONTROLLED_DEMO.md` for the exact policy. Calibration JSON is optional; missing/invalid calibration leaves speed unavailable. Optional per-analysis speed rules use a configured limit, tolerance and confirmation duration; blank limit disables events. `SAFE_DRIVE_HELMET_MODEL` can select a separate compatible local helmet model with the class order in `docs/HELMET_MODEL.md`; inference remains experimental. Jobs run one at a time in bounded subprocesses, with at most one queued job. Sessions, tracks, events and reviewer decisions persist in SQLite at `local_data/safe_drive.sqlite3`, and evidence files remain under ignored `local_data/`. Interrupted jobs become failed after restart and are not automatically retried. Worker diagnostics and private camera sources are not logged. Local research mode binds to loopback; use the authenticated production configuration for any approved hosted demo.

Live mode connects to the camera; it does not install software into camera firmware. The camera must expose an RTSP/RTSPS stream reachable from this computer, and OpenCV must support its transport and codec. This version has no ONVIF discovery or automatic reconnection and cannot guarantee real-time throughput on every computer. Some consumer cameras do not provide RTSP; check the camera or NVR settings.

If no camera is configured, the dashboard explicitly reports **Demo / Upload Mode**. To configure a default source, copy `config/camera.example.json` to the ignored `config/camera.json`, then set its `mode` and source fields. Environment variables override the JSON config: `SAFE_DRIVE_CAMERA_URL`, `SAFE_DRIVE_CAMERA_ID`, and `SAFE_DRIVE_CAMERA_MODE`. `SAFE_DRIVE_CAMERA_URL` takes priority for RTSP. Copy `.env.example` for reference; the app does not automatically load `.env`, so export values in the shell before launching. Never commit camera credentials. The current runner supports upload and RTSP capture; webcam parsing is present but webcam capture wiring is a later stage. Review actions require reviewer name/initials and are stored as verified or rejected decisions; they do not issue penalties.

The dashboard's shared session selector loads real saved tracks and events on any page. Overview includes searchable session history; Event Review combines type, severity, review-status and track-ID search with detailed inspection and persisted decisions. Light/dark theme preference is saved only in the browser. The mobile navigation opens from the menu button and supports Escape and keyboard focus.

Calibration JSON receives client-side structure checks, followed by the worker's geometry checks. A structure check does not establish camera calibration accuracy. The downloadable blank template contains intentionally invalid null coordinates until measured values are supplied. Missing recordings and failed requests have explicit states; missing measurements are never replaced with zero.

Frontend logic tests use Node's built-in runner: `node --test tests/test_ui_core.cjs`. The Flask API and core suite remains `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`. These checks do not constitute real AI evaluation.

## Calibration comes before speed claims

Copy `config/calibration.example.json` to a site-specific file. Replace the example correspondences with at least four well-spread, non-collinear points measured on the road plane. For evaluation, reserve independent measured distances/vehicles to estimate calibration error. A homography is valid only for a fixed camera and the road surface represented by those points; do not report speeds from the example values.

## Research status and scope

The source guide proposes combining helmet compliance, speed, near misses, OCR, and graduated penalties. A feature combination alone does not establish novelty. The research contribution should be narrowed after a reproducible literature review. A promising, testable direction is calibrated trajectory-based near-miss screening under domain shift, with uncertainty-aware speed estimates and subgroup analysis across daylight, night, rain, road geometry, and traffic density. Do not claim behavioral change from a video analytics prototype; that requires an ethically approved field study with a suitable comparison design.

No accuracy, safety, or publication claim is made by this repository. Results require annotated data, a stated split protocol, baselines, error analysis, and independent replication.

## Responsible-use limits

- Treat all detections and risk scores as research signals requiring human review.
- Do not use OCR output, track IDs, or risk scores to make an adverse decision about a person.
- Keep raw footage and camera credentials local, minimize retention, redact faces/plates in shared examples, and document permissions and applicable institutional review requirements.
- The scoring weights are illustrative policy parameters, not calibrated probabilities, legal rules, or validated fines.

## Suggested evaluation plan

See [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md) for a paper-ready experimental protocol. Minimum reporting should include detector precision/recall and mAP at a declared IoU, tracking HOTA/IDF1, speed MAE/RMSE against independent radar or surveyed ground truth, near-miss event precision/recall at a predefined event definition, calibration error, latency/FPS on named hardware, confidence intervals, and failure cases. Split by camera/site and time, not randomly by adjacent video frames.

See [`docs/PROJECT_REPORT.md`](docs/PROJECT_REPORT.md) for the current project report, implementation inventory, architecture, limits, and next research milestones.

See [`docs/HELMET_MODEL.md`](docs/HELMET_MODEL.md) for the custom helmet-state dataset, training, validation and optional inference workflow. No helmet weights or data are bundled. The current rider association is geometric and single-frame; it is experimental and does not produce a compliance event or verified decision.

Run the tests with `python -m unittest discover -s tests -v`. The tests cover camera configuration, geometry, speed estimation, temporal speed rules, track registry behavior, and SQLite event/session persistence. End-to-end CV evaluation still requires representative labeled footage and independent ground truth.

## License and data

No license or dataset is bundled yet. Before publishing or accepting external contributions, choose a license and confirm that every dataset/model weight permits the intended research and redistribution. Never commit private traffic footage, generated plate crops, credentials, or local databases.
# Final implementation report

See [SAFE-Drive final report](docs/SAFE_DRIVE_FINAL_REPORT.md) for verified features, setup, test results, model requirements, and current limitations. A PDF copy is available at [output/pdf/SAFE_DRIVE_FINAL_REPORT.pdf](output/pdf/SAFE_DRIVE_FINAL_REPORT.pdf).

## Capability status

- YOLO detection and DeepSORT tracking are integrated, but real inference has not been verified because compatible weights and sample traffic footage are not included.
- Real-world speed requires camera calibration; without it, speed is unavailable.
- Optional helmet classification requires compatible trained weights via `SAFE_DRIVE_HELMET_MODEL`; no such model is bundled.
- Accident detection is not implemented. Approach-risk screening is not an accident determination.
- Do not commit CCTV footage, credentials, databases, `.venv`, or model weights.
