# SAFE-Drive Research Toolkit

SAFE-Drive is a research prototype for analyzing traffic video using calibrated vehicle trajectories and transparent encounter-risk signals. This repository is a cleaned, research-oriented continuation of the supplied student prototype. It is not a validated enforcement product and does not issue fines or identify people.

## What is implemented

- Road-plane homography from measured pixel-to-metre correspondences.
- Timestamp-based speed estimates with warm-up and calibration-quality states.
- Pairwise 2-D closest-approach/TTC screening using each track's positions and velocities.
- Configurable, explainable risk scoring with missing-signal reporting.
- Append-only JSONL event logging with content-addressed event identifiers.
- Optional computer-vision and OCR dependencies, so analysis modules can be used without downloading model weights.

The starter code in `detector.py`, `main.py`, `near_miss.py`, `plate_reader.py`, `risk_engine.py`, and `speed_estimator.py` records the original prototype for comparison. `src/safe_drive/` contains the research modules. The original hard-coded pixel scale, horizontal-only TTC, plate-based automatic fine logic, and global near-miss attribution should not be used as scientific measurements.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
python -m pip install -e .
python -m pip install -e '.[vision]'  # only if running the video detector pipeline
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

The runner writes annotated video and pairwise approach-risk screening events. It does not read plates, infer helmet status, or issue fines. Track IDs are temporary within one clip. Review every event and validate calibration before interpreting the reported km/h values.

## Calibration comes before speed claims

Copy `config/calibration.example.json` to a site-specific file. Replace the example correspondences with at least four well-spread, non-collinear points measured on the road plane. For evaluation, reserve independent measured distances/vehicles to estimate calibration error. A homography is valid only for a fixed camera and the road surface represented by those points; do not report speeds from the example values.

## Research status and scope

The source guide proposes combining helmet compliance, speed, near misses, OCR, and graduated penalties. A feature combination alone does not establish novelty. The research contribution should be narrowed after a reproducible literature review. A promising, testable direction is calibrated trajectory-based near-miss screening under domain shift, with uncertainty-aware speed estimates and subgroup analysis across daylight, night, rain, road geometry, and traffic density. Do not claim behavioral change from a video analytics prototype; that requires an ethically approved field study with a suitable comparison design.

No accuracy, safety, or publication claim is made by this repository. Results require annotated data, a stated split protocol, baselines, error analysis, and independent replication.

## Responsible-use limits

- Treat all detections and risk scores as research signals requiring human review.
- Do not use OCR output, track IDs, or risk scores to make an adverse decision about a person.
- Keep raw footage local, minimize retention, redact faces/plates in shared examples, and document permissions and applicable institutional review requirements.
- The scoring weights are illustrative policy parameters, not calibrated probabilities, legal rules, or validated fines.

## Suggested evaluation plan

See [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md) for a paper-ready experimental protocol. Minimum reporting should include detector precision/recall and mAP at a declared IoU, tracking HOTA/IDF1, speed MAE/RMSE against independent radar or surveyed ground truth, near-miss event precision/recall at a predefined event definition, calibration error, latency/FPS on named hardware, confidence intervals, and failure cases. Split by camera/site and time, not randomly by adjacent video frames.

## License and data

No license or dataset is bundled yet. Before publishing or accepting external contributions, choose a license and confirm that every dataset/model weight permits the intended research and redistribution. Never commit private traffic footage, generated plate crops, credentials, or local databases.
