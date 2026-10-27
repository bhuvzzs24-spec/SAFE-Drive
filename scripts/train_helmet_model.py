"""Train a custom SAFE-Drive helmet-state detector with Ultralytics YOLO."""
from __future__ import annotations

import argparse
from pathlib import Path

EXPECTED = ["full_face_helmet", "half_face_helmet", "no_helmet", "uncertain"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Ultralytics dataset YAML")
    parser.add_argument("--base-model", required=True, help="explicit pretrained detector, e.g. yolo11n.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default=None, help="cuda device (0), cpu, or omit for auto")
    parser.add_argument("--project", type=Path, default=Path("training-runs/helmet"))
    parser.add_argument("--name", default="helmet-state-v1")
    args = parser.parse_args()
    if args.epochs < 1 or args.imgsz < 32 or args.batch < 1:
        parser.error("epochs, image size and batch must be positive")
    if not args.data.is_file():
        parser.error(f"dataset YAML not found: {args.data}")

    try:
        import yaml
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("Install training dependencies with: pip install -e '.[vision]'") from exc
    config = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    names = config.get("names") if isinstance(config, dict) else None
    if isinstance(names, dict):
        names = [names[index] for index in sorted(names)]
    if names != EXPECTED:
        parser.error(f"dataset classes must be ordered exactly as {EXPECTED}; received {names!r}")

    model = YOLO(args.base_model)
    result = model.train(data=str(args.data), epochs=args.epochs, imgsz=args.imgsz,
                         batch=args.batch, device=args.device, project=str(args.project),
                         name=args.name, plots=True, seed=42)
    best = Path(result.save_dir) / "weights" / "best.pt"
    print(f"Training finished. Best weights: {best.resolve()}")
    print("Do not enable inference until the independent validation protocol in docs/HELMET_MODEL.md passes.")


if __name__ == "__main__":
    main()
