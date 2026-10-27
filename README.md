# SAFE-Drive Research Toolkit

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

The first model run may download pretrained weights. Pin the exact model file and its SHA-256 in any experiment record. A pretrained general-object model does not detect helmet violations unless a validated helmet model is separately trained and supplied.

## Run one video

After creating a site-specific calibration file and installing the optional vision dependencies:

```bash
safe-drive video \
  --input path/to/traffic.mp4 \
  --calibration config/site-01.json \
  --output outputs/annotated.mp4 \
  --events outputs/events.jsonl
```

The runner writes annotated video, per-track summaries and screening events. It processes local video or RTSP/RTSPS input; add `--duration-sec 300` to bound a live session. Detector labels are mapped by name for supported cars, motorcycles, buses, trucks, and pedestrians; DeepSORT assigns session-local IDs to all of them. Pedestrians do not receive vehicle speed estimates or speed events. Calibration is optional: without valid measured calibration, detection/tracking continues and speed/TTC remain unavailable. A speed-limit event rule is disabled by default; set `--speed-limit-kmh`, `--speed-tolerance-kmh` and `--speed-confirmation-sec` to configure a rule. It does not read plates or issue fines. Review every event and validate calibration before interpreting km/h values.

## Local review dashboard

Install the `vision` extra, then run:

```bash
python app.py
```

Open `http://127.0.0.1:5170`. Choose **Video file** to upload a clip, or **Live IP camera** to enter an RTSP/RTSPS stream address and select a bounded capture duration. Calibration JSON is optional; without valid calibration, detections and tracks still run while speed is clearly unavailable. You can set an optional per-analysis speed limit, tolerance and minimum exceedance duration; blank limit disables speed events. Set `SAFE_DRIVE_HELMET_MODEL` to an existing compatible local weights file to enable experimental helmet-box inference on tracked pedestrians. The model must use the exact class order in `docs/HELMET_MODEL.md`; unmatched heads remain unclassified and ambiguous associations are marked uncertain. For live sessions, the event list updates as alerts appear; the annotated recording is available when the session ends or is stopped. Jobs run one at a time in a local background worker. Transient job status is held in memory, while sessions, vehicle and pedestrian tracks, events and review decisions persist in SQLite at `local_data/safe_drive.sqlite3`; uploaded clips and results remain as files under ignored `local_data/`. Camera stream addresses are passed to the worker for the session and omitted from event records and error logs. The server binds to loopback and is intended for local research use only. Do not expose it to a network.

Live mode connects to the camera; it does not install software into camera firmware. The camera must expose an RTSP/RTSPS stream reachable from this computer, and OpenCV must support its transport and codec. This version has no ONVIF discovery or automatic reconnection and cannot guarantee real-time throughput on every computer. Some consumer cameras do not provide RTSP; check the camera or NVR settings.

If no camera is configured, the dashboard explicitly reports **Demo / Upload Mode**. To configure a default source, copy `config/camera.example.json` to the ignored `config/camera.json`, then set its `mode` and source fields. Environment variables override the JSON config: `SAFE_DRIVE_CAMERA_URL`, `SAFE_DRIVE_CAMERA_ID`, and `SAFE_DRIVE_CAMERA_MODE`. `SAFE_DRIVE_CAMERA_URL` takes priority for RTSP. Copy `.env.example` for reference; the app does not automatically load `.env`, so export values in the shell before launching. Never commit camera credentials. The current runner supports upload and RTSP capture; webcam parsing is present but webcam capture wiring is a later stage. Review actions require reviewer name/initials and are stored as verified or rejected decisions; they do not issue penalties.

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
