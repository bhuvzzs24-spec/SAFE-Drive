# Helmet model: three-class detection and rider review

No labelled helmet dataset or trained helmet checkpoint is bundled. Training and real helmet inference have **not** been performed for this release. Synthetic tests verify interfaces, geometric association, temporal confirmation and persistence, not model accuracy.

## Exact model contract

The adapter is an **axis-aligned object detector**, not an image classifier. It accepts a trusted, existing local Ultralytics PyTorch detection `.pt` checkpoint compatible with the installed Ultralytics/PyTorch versions (for example a custom YOLOv8/YOLO11 detection model). It rejects classification, pose, segmentation, OBB, YAML architectures, URLs and ONNX/exported files. It never downloads missing weights or auto-installs dependencies. A `.pt` extension alone does not establish compatibility.

| Model ID | Required name | Visible head-region annotation |
| ---: | --- | --- |
| 0 | `full_face_helmet` | Worn helmet with visibly identifiable full face/chin coverage. |
| 1 | `half_face_helmet` | Worn open-face/half helmet with no full chin coverage. |
| 2 | `no_helmet` | Clearly visible bare rider head. Never infer this from absence. |

`uncertain` is an **abstention/review state**, not model class 3. Earlier four-class checkpoints are intentionally incompatible: re-annotate/retrain or explicitly validate a new three-class checkpoint; do not rename metadata to hide a different taxonomy. Standard COCO road-user checkpoints have person/motorcycle classes but do not supply this helmet taxonomy. No suitable licensed local helmet checkpoint was found. See the [official detection interface](https://docs.ultralytics.com/tasks/detect/) and [COCO class definitions](https://docs.ultralytics.com/datasets/detect/coco/).

## Dataset requirements

Supply permission-cleared JPEG/PNG frames with tightly drawn **head/helmet boxes**, not whole motorcycles. Include all three classes, representative small/distant heads, lighting, viewpoints, occlusion, helmet types and camera sites, plus genuinely negative images. Exclude ambiguous visible heads from the training export for adjudication rather than assigning a fourth class or silently treating them as negatives. Fully absent heads cannot receive a `no_helmet` label. Have independent annotators review a subset.

Split by capture session/camera/site **before** extracting frames; neighbouring frames and near-duplicate captures must not cross splits. Data preparation validates exact image duplicates and declared capture-group leakage; it cannot prove that different group IDs really represent independent sources or detect all visual near-duplicates. A human must audit the split and licence references.

Prepare an existing flat YOLO export:

```text
labelled-export/
  images/ frame001.jpg ...
  labels/ frame001.txt ...
manifest.csv
```

Each `.txt` line is `class_id x_center y_center width height`, normalized to [0,1], with a positive box fully inside the image. Use an explicit empty `.txt` for a verified negative frame. Only IDs 0/1/2 are accepted.

The user-supplied CSV must contain `image,split,group_id,license`. `image` is a unique basename; `split` is train/val/test; `group_id` identifies the original capture group; `license` references actual permission or licensing evidence. Do not put private credentials in any manifest. Every split needs labelled examples for all three classes; there is no universal minimum sufficient for accuracy. Dataset adequacy must be established empirically, with subgroup evaluation.

```sh
PYTHONPATH=src .venv/bin/python scripts/prepare_helmet_dataset.py \
  --source /private/labelled-export --manifest /private/manifest.csv \
  --output /private/datasets/helmet-v1
PYTHONPATH=src .venv/bin/python scripts/check_helmet_dataset.py \
  --data /private/datasets/helmet-v1/data.yaml
```

Preparation copies only supplied images/labels, never invents annotations or changes split assignments. The output directory must be new. A failed validation leaves the copied dataset for correction; it never overwrites the source. Result:

```text
helmet-v1/
  data.yaml                 # JSON syntax, also valid YAML
  manifest.csv
  images/{train,val,test}/
  labels/{train,val,test}/
```

The validator checks paths, headers, labels, class coverage, duplicates, declared groups and file hashes. Header checks do not establish complete image decoding; training must also successfully decode the inputs. Dataset hashes include image content, split membership and label hashes. Keep the versioned source manifest, licence evidence and annotation revision private.

## Training and held-out evaluation

Use the existing project environment. If vision dependencies have not been installed, install the declared extra intentionally: `.venv/bin/python -m pip install -e '.[vision]'`. Obtain a licensed **local detection base checkpoint** yourself. Do not pass a bare missing model name expecting a download.

```sh
PYTHONPATH=src .venv/bin/python scripts/train_helmet_model.py \
  --data /private/datasets/helmet-v1/data.yaml --base-model /private/models/base-detect.pt \
  --epochs 100 --imgsz 960 --batch 8 --device cpu --seed 42
PYTHONPATH=src .venv/bin/python scripts/validate_helmet_model.py \
  --model training-runs/helmet/helmet-three-class-v1/weights/best.pt \
  --data /private/datasets/helmet-v1/data.yaml --imgsz 960 --device cpu \
  --report evaluation-runs/helmet-v1/evaluation.json
```

These are reproducible commands, **not evidence that training happened**. Configuration defaults are documented in `config/helmet-training.example.json`. Training records base/checkpoint hashes, dataset fingerprint, arguments and package versions; fixed seed, deterministic options and zero data-loader workers reduce variability but do not guarantee identical results across hardware. Never tune on the test split. Evaluation maps metric-array positions through the model's class indices, reports missing metrics as null, and records the checkpoint fingerprint. Preserve confusion plots and test settings. Assess per-class precision/recall/AP and temporal rider-association precision, abstention coverage and calibration separately. No acceptance threshold or paper metric has been fabricated.

## Package and configure

```sh
PYTHONPATH=src .venv/bin/python scripts/export_helmet_model.py \
  --model training-runs/helmet/helmet-three-class-v1/weights/best.pt \
  --evaluation evaluation-runs/helmet-v1/evaluation.json \
  --output /private/models/helmet-v1.pt
export SAFE_DRIVE_HELMET_MODEL=/private/models/helmet-v1.pt
PYTHONPATH=src .venv/bin/python app.py
```

The packaging script validates the detection task, taxonomy and evaluation/checkpoint fingerprint, then copies `.pt` and its evaluation sidecar without overwriting an existing checkpoint. An evaluation file is not automatic quality approval. The current runner uses `.pt` directly; ONNX/TensorRT exports require a separately implemented and tested adapter and must not be configured here. See `config/helmet.example.env` for secret-free runtime settings.

## Rider association, abstention and events

The main road-user detector must detect and track **both persons and motorcycles**. It supplies persistent person and motorcycle IDs; no separate person/head detector is needed beyond the main road-user detector and the custom helmet/head detector. A motorcycle-only model cannot support rider helmet association. A person is still represented by the existing `pedestrian` detector class in storage; it is not proof the person is walking.

The head detector runs on the original BGR frame. At least 80% of a head box must lie within one person's upper 45%. Multiple heads/people, small heads (default minimum side 8 pixels), low confidence and absent observations abstain or return no observation. The rider gate additionally requires unique two-way lower-body/motorcycle overlap and geometric alignment. Predictions belong to the **person ID**, with a separate motorcycle reference. Nearby people without that association receive no helmet prediction. Multiple riders/pillions deliberately abstain. Geometry alone cannot reliably distinguish every pedestrian standing next to a bike from a seated rider: this remains experimental and needs labelled sequence/pose evaluation.

A pending `helmet_review` event needs the same class and motorcycle association for at least five observations spanning one second, with no gap above 0.5 seconds. Missing/uncertain heads, a bike/class change, reversed timestamps or a long gap reset confirmation. One event is emitted per stable segment. Every event preserves source frame/time, person ID, bike ID, confidence and duration. All three predicted classes can generate review records; no policy makes a half helmet automatically illegal. No single uncertain frame produces an event. Reviewer verification/rejection uses the existing authorized API and persists separately in SQLite. A reviewer decision is not an automatic legal finding.

Runtime controls: `SAFE_DRIVE_HELMET_CONFIDENCE` (0.5), `SAFE_DRIVE_HELMET_ASSOCIATION_CONFIDENCE` (0.65), `SAFE_DRIVE_HELMET_MIN_HEAD_PIXELS` (8), `SAFE_DRIVE_HELMET_CONFIRM_S` (1), `SAFE_DRIVE_HELMET_MIN_OBSERVATIONS` (5), `SAFE_DRIVE_HELMET_MAX_GAP_S` (0.5). Calibrate these against labelled held-out sequences. Keep checkpoints, datasets and training/evaluation outputs out of Git.
