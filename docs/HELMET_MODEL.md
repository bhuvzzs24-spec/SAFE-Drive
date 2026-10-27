# Custom helmet-state model workflow

## Current status

The repository does not include a helmet detector, annotated helmet dataset, or measured helmet performance. The application therefore does not output helmet compliance decisions. The scripts here establish a reproducible training and validation entry point; they do not create a trained model from absent data or enable helmet enforcement. The proposed four classes are experimental visual states, not legal conclusions.

## Dataset and annotation

Use only footage with permission for this research. Keep source video and identity-bearing imagery private. Create a versioned YOLO detection dataset with `images/train`, `images/val`, `images/test` and matching `labels/*` directories. Split by camera/site and capture session before extracting frames so adjacent frames from a single clip cannot leak across splits.

Each box should tightly cover the visible rider head/helmet region, not the whole motorcycle. Assign exactly one of the following labels:

| ID | Class | Annotation rule |
|---:|---|---|
| 0 | `full_face_helmet` | A visibly worn full-face helmet with face/chin coverage apparent. |
| 1 | `half_face_helmet` | A visibly worn open-face/half helmet without full chin coverage. |
| 2 | `no_helmet` | A clearly visible rider head with no helmet. |
| 3 | `uncertain` | Occluded, tiny, ambiguous, or insufficient evidence to distinguish the other states. |

Do not label absent/fully occluded heads as `no_helmet`; omit them from object detection labels. Have two annotators independently label a subset, adjudicate disagreements, and report class balance and agreement. Preserve the original split and annotation revision in experiment records.

Example `data.yaml`:

```yaml
path: /absolute/path/to/helmet_dataset
train: images/train
val: images/val
test: images/test
names:
  0: full_face_helmet
  1: half_face_helmet
  2: no_helmet
  3: uncertain
```

## Train and validate

Install the optional vision dependencies, including Ultralytics, then train from an explicitly chosen pretrained model:

```bash
python scripts/train_helmet_model.py --data /absolute/path/to/data.yaml --base-model yolo11n.pt --epochs 100 --device 0
python scripts/validate_helmet_model.py --model training-runs/helmet/helmet-state-v1/weights/best.pt --data /absolute/path/to/test-data.yaml --device 0
```

The training script checks class order and prints the produced weights path. Validation requires a held-out YAML with `test` split and reports class-wise precision, recall, AP50 and AP50-95; Ultralytics writes plots and a confusion matrix. Preserve logs, model hash, dataset version, package versions, split definition and test settings. Report confidence intervals and subgroup results for distance, occlusion, lighting, helmet color/style and camera site. Check the base model and dataset licenses before redistribution.

## Association and policy boundary

A helmet/head detector alone does not establish which motorcycle or rider it belongs to. This repository does not yet associate helmet boxes to rider identities or motorcycle tracks, temporally confirm helmet states, or emit helmet events. Those steps require rider-instance/pose association and a separately evaluated temporal policy. Never infer compliance from the nearest motorcycle, treat uncertain as compliant, or use predictions as legally verified violations. Any future integration must retain an explicit uncertain state and require human review.
