# Custom helmet-state model workflow

## Current status

The repository does not include trained helmet weights, an annotated helmet dataset, or measured helmet performance. An optional inference adapter is available, but it activates only when an existing local model is explicitly provided. It does not create a trained model from absent data or enable helmet enforcement. The four classes are experimental visual states, not legal conclusions.

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

## Optional inference and association boundary

A helmet/head detector alone does not establish which motorcycle or rider it belongs to. The optional adapter maps a detected head-region box to a tracked pedestrian only when its center falls in that person's upper 45% and the match is unique; ambiguous matches are `uncertain`, and no match produces no classification. This is a simple geometric association, not pose estimation, and has not been validated on crowded or occluded footage. There is no temporal confirmation or helmet event generation. Never infer compliance from the nearest motorcycle, treat `uncertain` or missing detections as compliant, or use predictions as legally verified violations.

To enable experimental frame-level inference, export the local weights path before starting the dashboard or CLI:

```bash
export SAFE_DRIVE_HELMET_MODEL=/absolute/path/to/best.pt
python app.py
```

The file must exist locally and expose the exact four class names and order above. The runner does not download helmet weights. Track summaries and annotated frames may include a helmet class only while this model is enabled; downstream review remains necessary. Until suitable model weights, test footage, and independent labels are supplied, no helmet inference result or performance claim is available.
