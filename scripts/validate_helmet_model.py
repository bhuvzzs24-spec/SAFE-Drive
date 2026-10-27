"""Run a held-out Ultralytics validation and print class-wise metrics."""
from __future__ import annotations

import argparse
from pathlib import Path

EXPECTED = ["full_face_helmet", "half_face_helmet", "no_helmet", "uncertain"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True, help="held-out test dataset YAML")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()
    if not args.model.is_file() or not args.data.is_file():
        parser.error("model weights and dataset YAML must both exist")
    try:
        import yaml
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("Install validation dependencies with: pip install -e '.[vision]'") from exc
    config = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    names = config.get("names") if isinstance(config, dict) else None
    if isinstance(names, dict):
        names = [names[index] for index in sorted(names)]
    if names != EXPECTED:
        parser.error(f"test classes must be ordered exactly as {EXPECTED}; received {names!r}")
    model = YOLO(str(args.model))
    metrics = model.val(data=str(args.data), split="test", imgsz=args.imgsz,
                        device=args.device, plots=True, verbose=True)
    box = metrics.box
    print("\nClass-wise held-out test metrics")
    for index, name in enumerate(EXPECTED):
        precision = float(box.p[index]) if len(box.p) > index else float("nan")
        recall = float(box.r[index]) if len(box.r) > index else float("nan")
        map50 = float(box.ap50[index]) if len(box.ap50) > index else float("nan")
        map5095 = float(box.ap[index]) if len(box.ap) > index else float("nan")
        print(f"{name}: precision={precision:.4f} recall={recall:.4f} AP50={map50:.4f} AP50-95={map5095:.4f}")
    print(f"Confusion matrix and plots: {getattr(metrics, 'save_dir', 'see Ultralytics validation output')}")
    print("Publish these values only with dataset version, split protocol, confidence/IoU settings, and uncertainty intervals.")


if __name__ == "__main__":
    main()
