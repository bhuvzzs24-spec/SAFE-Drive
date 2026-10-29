"""Explicit Ultralytics detection / deep-sort-realtime boundary contracts.

No model, framework, network or numerical imports occur at module import time.
"""
from dataclasses import dataclass
import math
from pathlib import Path


VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
DETECTION_CLASSES = {0: "pedestrian", **VEHICLE_CLASSES}  # COCO reference only
_SUPPORTED = {"person": "pedestrian", "pedestrian": "pedestrian", "car": "car",
              "motorcycle": "motorcycle", "motorbike": "motorcycle", "bus": "bus", "truck": "truck"}


def detector_class_map(names) -> dict[int, str]:
    """Resolve declared model labels; never assume custom models use COCO IDs."""
    labels = names.items() if isinstance(names, dict) else enumerate(names) if isinstance(names, (list, tuple)) else []
    result, seen = {}, set()
    for key, label in labels:
        try:
            index = int(key)
        except (ValueError, TypeError):
            raise ValueError("detector class IDs must be non-negative integers") from None
        if isinstance(key, bool) or str(index) != str(key) or index < 0 or index in seen:
            raise ValueError("detector class IDs must be unique non-negative integers")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("detector labels must be non-empty strings")
        seen.add(index)
        normalized = label.strip().lower()
        if normalized in _SUPPORTED:
            result[index] = _SUPPORTED[normalized]
    return result


def local_detector_weights(model_path) -> Path:
    """Support existing Ultralytics detection checkpoints only; never auto-download."""
    text = str(model_path).strip()
    if not text or "://" in text or Path(text).suffix.lower() != ".pt":
        raise ValueError("Supply an existing local Ultralytics detection .pt checkpoint; URLs, YAML and exports are unsupported.")
    path = Path(text).expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Detector weights are missing or empty: {path}. Supply your licensed local .pt file; no download is attempted.")
    return path


def clipped_box(values, width, height):
    box = [float(v) for v in values]
    if len(box) != 4 or not all(math.isfinite(v) for v in box):
        raise ValueError("xyxy boxes must contain four finite pixel coordinates")
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("xyxy boxes must have positive width and height")
    x1, y1, x2, y2 = box
    box = [max(0., min(width, x1)), max(0., min(height, y1)),
           max(0., min(width, x2)), max(0., min(height, y2))]
    return box if box[2] > box[0] and box[3] > box[1] else None


class YoloDetector:
    def __init__(self, model, confidence=0.35, device="cpu"):
        if getattr(model, "task", None) != "detect":
            raise ValueError("Detector checkpoint task must be 'detect'; classification, pose, segmentation and OBB models are unsupported.")
        if not math.isfinite(confidence) or not 0 < confidence <= 1:
            raise ValueError("confidence must be in (0, 1]")
        self.class_map = detector_class_map(model.names)
        if not self.class_map:
            raise ValueError("Detector labels do not include supported pedestrian or vehicle classes.")
        self.model, self.confidence, self.device = model, confidence, device
        self.declared_ids = {int(key) for key in model.names} if isinstance(model.names, dict) else set(range(len(model.names)))

    def detect(self, frame):
        """BGR HxWx3 -> [([left, top, width, height], confidence, class_name)]."""
        if len(frame.shape) != 3 or frame.shape[2] != 3 or frame.dtype.name != "uint8" or min(frame.shape[:2]) <= 0:
            raise ValueError("detector input must be a nonempty uint8 HxWx3 BGR frame")
        height, width = frame.shape[:2]
        results = self.model(frame, verbose=False, conf=self.confidence, device=self.device)
        if len(results) != 1 or tuple(results[0].orig_shape) != (height, width):
            raise ValueError("detector result must match the original frame dimensions")
        if results[0].boxes is None:
            raise ValueError("detector did not return axis-aligned detection boxes")
        detections = []
        for box in results[0].boxes:
            raw_cls, conf = float(box.cls[0]), float(box.conf[0])
            if not math.isfinite(raw_cls) or raw_cls < 0 or not raw_cls.is_integer():
                raise ValueError("detector returned an invalid class ID")
            if not math.isfinite(conf) or not 0 <= conf <= 1:
                raise ValueError("detector returned invalid confidence")
            cls = int(raw_cls)
            if cls not in self.declared_ids:
                raise ValueError("detector returned a class ID absent from its declared labels")
            if cls not in self.class_map or conf < self.confidence:
                continue
            coords = clipped_box(box.xyxy[0].cpu().numpy(), width, height)
            if coords is None:
                continue
            x1, y1, x2, y2 = coords
            detections.append(([x1, y1, x2-x1, y2-y1], conf, self.class_map[cls]))
        return detections


@dataclass(frozen=True)
class TrackObservation:
    track_id: str
    bbox_xyxy: list[float]
    object_class: str
    confidence: float | None


def observed_tracks(tracker, detections, frame):
    """Advance once per frame, including empty frames. Exclude predictions/tentatives.

    Use the matched detection's original pixel box, not Kalman extrapolation, for
    the road contact point. Requires deep-sort-realtime's orig_strict API.
    """
    observations, seen = [], set()
    for track in tracker.update_tracks(detections, frame=frame):
        if not track.is_confirmed() or track.time_since_update != 0:
            continue
        box = track.to_ltrb(orig=True, orig_strict=True)
        if box is None:
            continue
        box = clipped_box(box, frame.shape[1], frame.shape[0])
        if box is None:
            continue
        tid, label = str(track.track_id), track.get_det_class()
        if not tid or tid in seen or label not in _SUPPORTED.values():
            raise ValueError("tracker returned duplicate IDs or an unsupported detection class")
        confidence = track.get_det_conf()
        confidence = float(confidence) if confidence is not None else None
        if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("tracker returned invalid confidence")
        seen.add(tid)
        observations.append(TrackObservation(tid, box, label, confidence))
    return observations
