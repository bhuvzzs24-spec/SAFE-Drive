# Research plan: SAFE-Drive

## Research question

How reliably can calibrated monocular trajectories screen for vehicle-pair near-miss events across different fixed-camera sites and lighting conditions, and how much does uncertainty-aware speed gating improve the precision of those alerts?

This question is more defensible than treating a four-feature integration as a novelty claim. Confirm the gap with a fresh literature review before committing to a submission.

## Proposed contributions (to validate)

1. A reproducible video pipeline that maps tracked road-contact points into a calibrated metric plane.
2. A pair-specific closest-approach/TTC screen, with speed validity and missing-signal state exposed in every event.
3. A cross-site evaluation with a clear near-miss annotation policy, calibration-error reporting, and ablations.

These are proposed contributions, not established results.

## Data and annotation

- Obtain documented permission for each video source; record camera position, lens changes, frame rate, weather, lighting, and road geometry.
- Sample clips across multiple sites and temporal conditions. Keep all clips from a site/session in one split to prevent leakage.
- Have two annotators independently label vehicle tracks and near-miss intervals using a written operational definition (e.g., conflict point, post-encroachment time, and minimum separation). Adjudicate disagreements and report inter-rater agreement.
- Collect independent speed ground truth for a subset (radar, instrumented vehicle, or surveyed timing segment). Do not use the same landmarks to both fit and evaluate the homography.
- Exclude or redact plate/face identity from the research dataset unless essential, explicitly authorized, and ethically approved.

## Baselines and ablations

- Baselines: box overlap; image-space TTC; calibrated constant-velocity TTC; and an established public benchmark method appropriate to the selected dataset.
- Ablations: no calibration vs calibrated ground plane; no temporal smoothing vs smoothing; alternate track association; and confidence/uncertainty gating on vs off.
- Use fixed detector/tracker versions across comparisons. Report results by site, illumination, road-user class, occlusion level, and traffic density.

## Metrics

- Detection: precision, recall, AP/mAP with IoU thresholds and class definitions stated.
- Tracking: HOTA and IDF1, plus ID switches.
- Speed: MAE, RMSE, bias, and error distribution against independent ground truth; include calibration residuals.
- Conflict detection: event-level precision/recall/F1, false alerts per camera-hour, and lead-time distribution at pre-registered thresholds.
- Systems: end-to-end latency and throughput on named hardware, with warm-up/inference settings.
- Uncertainty: calibration plots or selective risk/coverage when confidence estimates are added.

Report 95% confidence intervals using bootstrap resampling by clip or site, not by frame. Define thresholds on validation data and freeze them before test evaluation.

## Paper honesty checklist

- Literature review searched multiple indexes with date and query strings retained; claimed gaps checked against closest systems.
- Dataset license/consent, split manifest, annotation handbook, software/model versions, and configuration archived.
- No invented metrics, unsupported “first” claim, or behavioral-change conclusion without a controlled human study.
- Limitations include monocular calibration drift, camera motion, occlusion, tracker ID switches, detector domain shift, annotation ambiguity, and non-constant motion.
