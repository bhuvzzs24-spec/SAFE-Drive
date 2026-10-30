# SAFE-Drive completion acceptance — 30 October 2026

This release preserves the Flask application, existing API paths, SQLite schema/history and premium nine-page UI. It does not establish that SAFE-Drive is fully AI-operational. No deployment, hosting charge, arbitrary model download or dataset download was performed.

## Fixed and connected

- Three-class Ultralytics **detection** `.pt` helmet contract: `0=full_face_helmet`, `1=half_face_helmet`, `2=no_helmet`. `uncertain` is an abstention, never a trained fourth class. Incompatible task/taxonomy, invalid boxes/classes/confidence and unsupported formats fail closed.
- Conservative person/head plus motorcycle association, excluding unassociated people and abstaining on ambiguous riders/heads, low confidence and small heads. Predictions retain the person ID and reference a separate motorcycle ID. Geometry is experimental and cannot prove that every candidate is riding; pillion/crowded scenes abstain.
- Temporal helmet screening creates pending `helmet_review` records only after consistent observations. Missing/uncertain observations, class/bike changes, long gaps and non-monotonic times reset confirmation. Records preserve original frame/time, confidence and confirmation duration. Existing authorized reviewer decisions remain separate and persist.
- Dataset preparation/validation, capture-group split checks, duplicate-image detection, YOLO annotation validation, image/label fingerprints, local-only training, class-index-correct held-out evaluation and checkpoint packaging. Exact setup, taxonomy, annotation and commands are in `HELMET_MODEL.md`. There is no invented dataset, trained checkpoint or performance table.
- Helmet observations use actual persisted tracks/events in the existing page. Event search/type/severity/review filters understand helmet records and both referenced tracks. Analytics supports entire-workspace or authorized selected-session scope; unavailable values are not converted to fabricated measurements.
- Settings distinguishes configured path, nonempty file, supported format, dependency-module discovery, model-load verification and inference verification. Dependency discovery is explicitly weaker than native import testing. The private view shows the actual configured database path; public users get no private path or records.
- Missing model files now produce immediate, privacy-safe persisted job failures. Initial RTSP connections have bounded retries and existing open/read timeouts. A stream interruption requires a new session, preserving timing/track provenance. Camera calibration must match the registered camera ID. Client-supplied camera URLs and public camera use remain denied.
- Approach-risk thresholds are configurable and recorded with events/manifests; invalid/same track pairs are rejected. Near-miss screening remains separate from accident detection. Existing calibrated speed gating, optional speed-rule thresholds and human review remain intact.
- Premium landing, all nine views, responsive video sizing, light/dark workspace support and reduced-motion handling are retained. The analytics scope selector now wraps correctly on tablets.

## Validation categories and observed outcomes

Final automated run: **100 Python tests passed in 3.934 seconds; 10 frontend tests passed in 92.295 milliseconds; no skips, failures or errors.** JavaScript syntax checks also passed. These results use the verified local source copy and existing interpreter described below; the blocked direct-checkout/native checks are explicitly separated.

- **Unit tests:** real geometry, homography validation, speed units/timestamps/gaps, rule confirmation, risk pairs, class/box mapping, abstention and temporal confirmation.
- **Synthetic/mocked integration:** supplied detector/track/video stubs exercise the complete orchestration, annotations, track histories, helmet events, JSONL, run provenance and real SQLite. These are not real inference or detector metrics.
- **Real API/storage checks:** Flask starts on a loopback-only QA port with a disposable database. Health returns `{"status":"ok"}`. CSS, JavaScript and the local JPEG return 200 with correct MIME types. Invalid container upload returns 400; a generated 461,104-byte AVI returns 202, progresses through running to failed and persists the specific absent-detector-weights explanation with zero detections. That does not verify video decoding or inference.
- **Process restart check:** two separate Python processes use the same disposable SQLite file. The second process verifies saved session, track, helmet event, reviewer/time, scoped analytics and failed recovery of an interrupted queued session through Flask APIs. No user data is changed.
- **Browser checks:** all nine views checked at 375/820/1280 pixels; the observed analytics overflow was fixed and retested. No normal-navigation JavaScript errors observed. Synthetic records are explicitly named “Synthetic UI QA — no inference”. Helmet review saves and survives reload, associated track references work, and selected-session analytics changes correctly on session switching. Prior premium landing/navigation/theme/empty/upload checks are preserved; no fabricated results are added.
- **Native vision smoke:** attempted the existing real OpenCV/DeepSORT synthetic-codec/interface smoke with a 35-second limit. It timed out during OpenCV native import before any frame or tracker validation. It is **blocked**, not passed.
- **Direct checkout test attempt:** bounded at 50 seconds, it timed out reading an offloaded source module during test discovery. The complete suite is instead run against the checksum-matched local QA source copy with the same project Python interpreter and existing dependency-source cache. No environment was recreated and no packages were reinstalled. This filesystem limitation still affects direct checkout startup/imports.

Reproducible project commands when the checkout and existing virtual environment are locally available:

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
node --test tests/test_ui_core.cjs
PYTHONPATH=src PORT=5170 .venv/bin/python app.py
# http://127.0.0.1:5170/ or http://127.0.0.1:5170/#analysis
```

The actual QA command uses that same `.venv/bin/python` with `-S` and explicit `PYTHONPATH` entries for the local source copy, existing dependency cache and original site-packages, avoiding the offloaded virtual-environment startup file. The recorded command/log is retained with the local acceptance artifacts. QA servers use disposable storage; the user's existing server/database is untouched.

## Missing prerequisites and remaining risks

1. A trusted, licensed local Ultralytics road-user **detection `.pt`** checkpoint whose declared classes include supported vehicles and persons. None was found in the supplied project folders. The bundled DeepSORT appearance checkpoint exists, but native inference/tracking is not validated by its presence.
2. A permission-cleared traffic video with readable codec, trustworthy timestamps and representative road users. No suitable real traffic footage was supplied. Synthetic video/boxes are never reported as live AI output.
3. Camera-specific measured correspondences, matching image dimensions/camera ID and independent distance/speed ground truth for field validation. Synthetic homography tests do not establish site accuracy.
4. A licensed labelled three-class head/helmet dataset, independent camera/session splits and held-out sequence labels, plus a compatible trained/evaluated checkpoint. **Helmet training did not occur. Real helmet inference was not tested.** There is no validated pretrained helmet model bundled.
5. An explicitly authorized registered RTSP/RTSPS source and permitted IP, credentials, network access, compatible codec and camera calibration. **Real camera operation was not tested.** OpenCV does not reliably distinguish authentication failures from every network/codec error; diagnostics deliberately avoid exposing private URLs. Network egress controls remain required in a private deployment.
6. macOS must make the checkout, `.venv` files and native libraries locally available. Intermittent `hidden,compressed,dataless` file reads/imports remain an environment blocker; the native smoke failed for this reason. Native runtime, real inference, crowded rider association, field calibration and incident accuracy need separate evaluation.

No accident detector, automated legal violation, identity inference, enforcement, validated helmet compliance count or public deployment is claimed. Existing deployment files and controlled-demo protections remain; deployment is outside this authorized release.

Earlier project reports/PDF are historical snapshots. This document and the Git commit containing it describe the current implementation; the commit ID is supplied by Git metadata and the final publication response rather than hardcoded into its own content.
