# Reproducible vision integration

This guide describes the current runner, not a detector accuracy or accident-detection claim. The Flask application and CLI share `safe_drive.cli.run_video`. No weights, footage, or independent road survey is bundled. Keep experimental artifacts outside Git and outside the dashboard database unless they are genuine analysis sessions.

## Required inputs and environment

Reuse the project's existing `.venv`. Do not create a second environment or reinstall a working stack. Check dependencies first:

```bash
.venv/bin/python --version
.venv/bin/python -m pip check
.venv/bin/python -m pip freeze > /tmp/safe-drive-environment.txt
```

Only if the vision dependencies are absent, install into that interpreter:

```bash
.venv/bin/python -m pip install -e '.[vision]'
```

Supply these local inputs explicitly:

1. A trusted, licensed Ultralytics YOLO **axis-aligned detection `.pt` checkpoint** compatible with the installed Ultralytics/PyTorch versions. Preserve its origin, licence, training classes and checksum. Never load an untrusted pickle-based checkpoint. A bare filename works only if that file already exists in the working directory. No automatic model download or package installation is requested by SAFE-Drive.
2. A short, lawfully usable fixed-camera video containing relevant road users, with reliable timestamps. Preserve its licence/permission and SHA-256. Synthetic shapes can test plumbing, but cannot validate vehicle detection accuracy.
3. For metric speed or approach screening: a measured road-plane calibration from that exact camera view and resolution, plus separately surveyed distances and independent speed ground truth for evaluation. Without calibration, tracking runs and metric signals remain unavailable.
4. DeepSORT's MobileNetV2 appearance checkpoint. Normally it is bundled at `deep_sort_realtime/embedder/weights/mobilenetv2_bottleneck_wts.pt`. To supply the same compatible architecture's weights elsewhere, export `SAFE_DRIVE_TRACKER_WEIGHTS=/absolute/path/to/mobilenetv2_bottleneck_wts.pt`. Detector and appearance weights are different files.

Installed package metadata observed in this checkout: Python 3.13.15, NumPy 2.5.4, OpenCV 5.0.0.93, Ultralytics 8.4.190, deep-sort-realtime 1.3.2, PyTorch 2.14.1 and torchvision 0.29.1. This is an inventory, **not a claim that native imports or inference succeeded**. Pin the full dependency snapshot of a successful run when replicating it on another computer.

## Detector and tracker contracts

`YoloDetector.detect(frame)` receives a uint8 BGR `H×W×3` frame. It calls `YOLO(local_path, task='detect')`, then `model(frame, verbose=False, conf=threshold, device=device)`. Default device is CPU, overridable with `--device` / `SAFE_DRIVE_DEVICE`. The checkpoint's loaded task must actually be `detect`; merely passing `task='detect'` cannot convert a different trained task.

Supported runner format: **existing local `.pt` detection checkpoints only**. The underlying Ultralytics library supports additional exports/backends, but ONNX, TensorRT, OpenVINO, CoreML, YAML, remote model URLs, pose, classification, segmentation and oriented boxes have not been integrated into this contract and are rejected. A `.pt` extension alone does not establish compatibility; the model must load, expose the correct task/labels and return the required results.

Exactly one result must report `orig_shape == (H,W)` and axis-aligned `boxes`. Each box exposes `cls[0]`, `conf[0]`, `xyxy[0].cpu().numpy()`. Coordinates are original-frame pixels, **not normalized coordinates or letterboxed network coordinates**. Supported declared names, case-insensitively: `person`/`pedestrian`, `car`, `motorcycle`/`motorbike`, `bus`, `truck`. These map to pedestrian/car/motorcycle/bus/truck. No COCO numeric IDs are assumed. Known unsupported classes are ignored; undeclared class IDs, invalid confidences and nonfinite/reversed boxes fail clearly. Boxes are clipped to frame bounds, and empty clipped boxes are discarded. Empty detection lists remain empty.

DeepSORT receives `([left, top, width, height], confidence, class_name)` once for **every decoded frame**, including frames without detections, and the original BGR frame for appearance embedding. Settings are explicit: MobileNetV2, BGR, CPU, float32, `max_age=30`, `n_init=3`. Do not interpret those frame-based settings as fixed seconds when source FPS varies. DeepSORT does not guarantee global IDs, class-consistent association, or identity through every occlusion. Its IDs are local to one run; assess identity switches on labeled footage.

Only confirmed tracks with `time_since_update == 0` and a matched original box from `to_ltrb(orig=True, orig_strict=True)` are measured. Kalman predictions and tentative IDs are not detections. A bottom-centre pixel contact point is used for road projection; box centres are retained only as display trails. Pedestrians are tracked but do not receive vehicle speed estimates or speed-limit events. Helmet inference is a separate optional experimental model, with the requirements in `HELMET_MODEL.md`.

## Timing, calibration and speed

Files default to OpenCV `CAP_PROP_POS_MSEC` after each successful read. Timestamps are normalized to the first frame and must be finite, nonnegative, and strictly increasing. No silent fallback hides missing/reversed/repeated timestamps. For a source independently verified as constant-frame-rate, `--timestamp-mode cfr` explicitly selects `frame_index / FPS`; the dashboard equivalent is `SAFE_DRIVE_TIMESTAMP_MODE=cfr`. Live streams use host monotonic arrival intervals, which include network/decode delay and are **not validated camera capture timestamps**. Camera speed estimates need separate validation.

Annotated output uses OpenCV's `mp4v` encoder and a constant-rate time grid. Timestamp-based frame holds/drops keep variable-rate input evidence aligned to within roughly one output frame. Gaps over ten seconds fail rather than allocate an unbounded recording. The output has no audio. Codec support and browser playback depend on the installed OpenCV/OS codecs; a successful file write alone does not prove browser playback.

Calibration JSON:

```json
{
  "camera_id": "surveyed-camera-id",
  "image_size_px": [1920, 1080],
  "image_points_px": [[0, 0], [100, 0], [100, 100], [0, 100]],
  "road_points_m": [[0, 0], [10, 0], [10, 20], [0, 20]],
  "validation_distances": [
    {"image_points_px": [[10, 10], [40, 30]], "distance_m": 5}
  ]
}
```

These numbers are **synthetic analytic examples**, not a deployment calibration. Replace all correspondences, resolution, hold-out endpoints and distances with measured values. Optional `image_size_px` must match the decoded frame resolution; a mismatch disables metric signals. Without that field, matching view/resolution is the operator's responsibility. Do not use a moving/panning camera, off-plane road users or a different crop/lens configuration with the same homography.

The implementation caches a Hartley-normalized DLT homography. It rejects insufficient, nonfinite, duplicated, collinear or rank-deficient correspondences and projective-horizon points. Algebraic validity does **not** prove survey accuracy or physical validity. Run:

```bash
PYTHONPATH=src .venv/bin/python -m safe_drive.cli calibration-check \
  --calibration /absolute/path/to/measured-camera.json
```

It reports fitting RMSE separately from supplied independent distance errors in metres and relative error. Four fitting points can have near-zero residual with a completely wrong survey. Hold-out distances must not be reused as fitting constraints. Establish an acceptable error tolerance from the experiment; the command does not declare a scientific pass threshold.

Speed is displacement in metres / measured elapsed seconds × **3.6** for km/h. The estimator needs at least two points and a 0.25-second baseline, targets a one-second baseline, rejects baselines beyond two seconds, and median-smooths up to five estimates. Initial/insufficient history returns `None` with `warming_up`. Timestamp resets, long gaps and implausible jumps clear smoothing/trajectory state; missing measurements cannot confirm continuous speeding. The default plausibility ceiling is 250 km/h, not a calibrated uncertainty bound. A track's last estimate is not its maximum speed. Speed events require the configured limit + tolerance to be exceeded for the confirmation duration; all require review. Approach screening waits for measured velocity history and excludes diverging/stationary pairs. It is a constant-velocity research screen, **not accident detection**.

## Run a real, reproducible experiment

From the repository directory, use new output paths for each run:

```bash
PYTHONPATH=src .venv/bin/python -m safe_drive.cli video \
  --input /absolute/path/to/licensed-traffic.mp4 \
  --model /absolute/path/to/compatible-detection.pt \
  --calibration /absolute/path/to/measured-camera.json \
  --device cpu --confidence 0.35 \
  --speed-limit-kmh 50 --speed-tolerance-kmh 5 --speed-confirmation-sec 1 \
  --output local_data/evaluation-01/annotated.mp4 \
  --events local_data/evaluation-01/events.jsonl
```

Omit calibration and speed-rule flags to verify uncalibrated tracking first. For the Flask app, `export SAFE_DRIVE_MODEL=/absolute/path/to/compatible-detection.pt`, then `PYTHONPATH=src .venv/bin/python app.py`; open `http://127.0.0.1:5170/`, supply the same local model path and upload inputs. No API contract or database schema change is required. CLI runs produce files; dashboard runs additionally persist tracks/events/reviews in SQLite.

Artifacts:

- `annotated.mp4`: actual detection labels, confirmed track IDs and available calibrated speed labels.
- `annotated.tracks.jsonl`: one row per decoded frame with source frame index, timestamp, detection count and actual observed tracks, original boxes, projected positions, velocities, speed and quality. No dummy rows for missed tracks.
- `events.jsonl`: speed-rule and experimental approach-screen events, or an empty file for zero events. Risk encounters are dictionaries compatible with SQLite callbacks.
- `annotated.run.json`: completed/stopped run summary, model/input/calibration/appearance-model SHA-256, code hashes, package/Python/platform inventory, selected device, class map, thresholds, FPS, image dimensions and timestamp policy. It contains wall elapsed seconds and aggregate processed frames/sec for the decode→inference→tracking→annotation/write loop, excluding model initialization and final artifact hashing. This is not detector-only inference FPS or an accuracy metric. Do not report throughput from stub tests.

Existing artifacts are never overwritten or appended across runs. A failure can leave partial files; no completed run manifest is written. A stop request is recorded as stopped. Check the manifest and inspect the output before treating a recording as complete. Retain exact input permissions, version snapshot and hashes with the run. Store calibration survey notes and hardware/GPU details alongside it.

Inspect the annotated recording at occlusions, crossings and re-entry; match frame-log IDs against manually labeled identities. Report ID switches/IDF1/HOTA only with appropriate reference annotations and a declared evaluation protocol. Evaluate detector precision/recall on labeled held-out frames, speed MAE/RMSE against independent radar/surveyed timing, and approach-screen precision/recall against a predefined human-reviewed event definition. Preserve no-calibration and failure cases. No such accuracy/performance results are inferred from unit tests.

## Three distinct validation levels

1. **Deterministic automated tests:**

   ```bash
   PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
   node --test tests/test_ui_core.cjs
   git diff --check
   ```

   `test_vision_interfaces.py` uses fake models/tracks; `test_video_pipeline.py` stubs detector, tracker and codecs while running actual geometry, speed, event JSONL and SQLite code. They validate plumbing, not real inference. Analytic calibration/speed/risk tests use known synthetic coordinates/trajectories.

2. **Optional native I/O + real DeepSORT API smoke test, without any detector:**

   ```bash
   PYTHONPATH=src .venv/bin/python -u scripts/vision_io_smoke.py \
     --output-dir /tmp/safe-drive-synthetic-01 --timeout 120
   ```

   Creates a small synthetic shape video, supplies explicit known rectangles and synthetic embeddings to the actual DeepSORT library, renders watermarked tracking output, decodes it again and records identity consistency. No detector or appearance model is run; no dashboard records are created. Never present this as vehicle detection. The script fails explicitly on import, codec, frame-count or identity problems. Use a new directory each time.

3. **Actual inference:** the real-video command above, using supplied compatible weights and licensed footage. Only this level exercises the real detector and appearance model. It remains separate from fixtures and requires independent annotations/calibration to evaluate accuracy.

## Current verification record

No compatible local detector weights or traffic video were found in the project or supplied source folder during this phase; no files were downloaded. Real YOLO inference, real-footage identity consistency, camera capture, detector accuracy, speed accuracy and throughput remain unverified. Bounded native-import probes timed out while reading NumPy modules; installed version metadata alone does not establish a working native vision runtime. See the task completion report for the actual test and native-smoke outcomes. Accident detection is not implemented.
