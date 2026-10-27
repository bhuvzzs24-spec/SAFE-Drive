"""Optional custom helmet-state inference and conservative rider association."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

HELMET_CLASSES = ("full_face_helmet", "half_face_helmet", "no_helmet", "uncertain")


def ordered_class_names(names: Any) -> tuple[str, ...]:
    if isinstance(names, dict):
        try:
            names = [names[key] for key in sorted(names, key=lambda key: int(key))]
        except (TypeError, ValueError):
            raise ValueError("helmet model class names must use consecutive numeric IDs") from None
    if not isinstance(names, (list, tuple)):
        raise ValueError("helmet model must expose an ordered class-name list")
    return tuple(str(name) for name in names)


@dataclass(frozen=True)
class HelmetDetection:
    bbox_xyxy: tuple[float, float, float, float]
    class_name: str
    confidence: float


class HelmetInference:
    """Loads only explicit local weights; missing weights never trigger a download."""

    def __init__(self, model: Any, confidence: float = 0.35,
                 association_confidence: float = 0.5):
        names = ordered_class_names(getattr(model, "names", None))
        if names != HELMET_CLASSES:
            raise ValueError(f"helmet model classes must be ordered as {HELMET_CLASSES}; received {names}")
        self.model = model
        self.confidence = confidence
        self.association_confidence = association_confidence

    @classmethod
    def from_path(cls, weights: str | Path) -> "HelmetInference":
        path = Path(weights).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"helmet weights do not exist: {path}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Helmet inference requires the optional vision dependencies.") from exc
        return cls(YOLO(str(path)))

    def detect(self, frame) -> list[HelmetDetection]:
        result = self.model(frame, verbose=False, conf=self.confidence)[0]
        detections = []
        for box in result.boxes:
            class_id = int(box.cls[0])
            class_name = ordered_class_names(self.model.names)[class_id]
            xyxy = tuple(float(value) for value in box.xyxy[0].cpu().numpy())
            detections.append(HelmetDetection(xyxy, class_name, float(box.conf[0])))
        return detections

    def associate(self, people: Sequence[tuple[str, Sequence[float]]],
                  detections: Sequence[HelmetDetection]) -> dict[str, str | None]:
        """Associate head-region boxes to a unique person's upper body.

        A detection that overlaps multiple person head-regions or multiple
        detections for one person becomes uncertain. No match means no result,
        never an inferred no-helmet state.
        """
        assigned: dict[str, list[HelmetDetection]] = {str(track_id): [] for track_id, _ in people}
        ambiguous: set[str] = set()
        for detection in detections:
            x1, y1, x2, y2 = detection.bbox_xyxy
            center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
            candidates = []
            for track_id, box in people:
                px1, py1, px2, py2 = map(float, box)
                head_bottom = py1 + max(0.0, py2 - py1) * 0.45
                if px1 <= center_x <= px2 and py1 <= center_y <= head_bottom:
                    candidates.append(str(track_id))
            if len(candidates) == 1:
                assigned[candidates[0]].append(detection)
            elif len(candidates) > 1:
                ambiguous.update(candidates)

        result: dict[str, str | None] = {}
        for track_id, _ in people:
            key = str(track_id)
            matches = assigned[key]
            if key in ambiguous or len(matches) > 1:
                result[key] = "uncertain"
            elif not matches:
                result[key] = None
            elif matches[0].confidence < self.association_confidence:
                result[key] = "uncertain"
            else:
                result[key] = matches[0].class_name
        return result
