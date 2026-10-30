"""Three-class head detector and conservative, temporal rider review screening.

Uncertain is an abstention, never a fourth trained class or legal decision.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import os
from pathlib import Path
from .vision import clipped_box, local_detector_weights

HELMET_CLASSES = ("full_face_helmet", "half_face_helmet", "no_helmet")


def ordered_class_names(names):
    if isinstance(names, dict):
        if set(names) == set(range(len(names))):
            names = [names[i] for i in range(len(names))]
        elif set(names) == {str(i) for i in range(len(names))}:
            names = [names[str(i)] for i in range(len(names))]
        else:
            raise ValueError("helmet model class names must use consecutive numeric IDs starting at zero")
    if not isinstance(names, (list, tuple)) or not all(isinstance(n, str) for n in names):
        raise ValueError("helmet model must expose an ordered class-name list")
    return tuple(names)


@dataclass(frozen=True)
class HelmetDetection:
    bbox_xyxy: tuple[float, float, float, float]
    class_name: str
    confidence: float


@dataclass(frozen=True)
class HelmetAssessment:
    class_name: str | None
    confidence: float | None
    reason: str
    motorcycle_track_id: str | None = None


def valid_box(values):
    box = tuple(float(v) for v in values)
    if len(box) != 4 or not all(math.isfinite(v) for v in box) or box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("helmet association requires finite positive xyxy boxes")
    return box


def overlap(a, b):
    return max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))


class HelmetInference:
    """Ultralytics axis-aligned detection .pt only; never downloads checkpoints."""
    def __init__(self, model, confidence=.5, association_confidence=.65, min_head_pixels=8):
        names = ordered_class_names(getattr(model, "names", None))
        if names != HELMET_CLASSES:
            raise ValueError(f"helmet model classes must be ordered as {HELMET_CLASSES}; received {names}")
        if getattr(model, "task", None) != "detect":
            raise ValueError("helmet checkpoint must be a detection model, not a classifier")
        if not all(math.isfinite(v) and 0 < v <= 1 for v in (confidence, association_confidence)):
            raise ValueError("helmet confidence thresholds must be in (0, 1]")
        if not math.isfinite(min_head_pixels) or min_head_pixels <= 0:
            raise ValueError("minimum head size must be positive and finite")
        self.model, self.confidence = model, confidence
        self.association_confidence, self.min_head_pixels = association_confidence, min_head_pixels

    @classmethod
    def from_path(cls, weights: str | Path):
        path = local_detector_weights(weights)
        os.environ.update(YOLO_AUTOINSTALL="false", YOLO_OFFLINE="true")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Helmet inference requires the optional vision dependencies.") from exc
        return cls(YOLO(str(path), task="detect"),
                   float(os.environ.get("SAFE_DRIVE_HELMET_CONFIDENCE", ".5")),
                   float(os.environ.get("SAFE_DRIVE_HELMET_ASSOCIATION_CONFIDENCE", ".65")),
                   float(os.environ.get("SAFE_DRIVE_HELMET_MIN_HEAD_PIXELS", "8")))

    def detect(self, frame):
        if len(frame.shape) != 3 or frame.shape[2] != 3 or frame.dtype.name != "uint8" or min(frame.shape[:2]) <= 0:
            raise ValueError("helmet input must be a nonempty HxWx3 uint8 BGR frame")
        height, width = frame.shape[:2]
        results = self.model(frame, verbose=False, conf=self.confidence, device=os.environ.get("SAFE_DRIVE_DEVICE", "cpu"))
        if len(results) != 1 or tuple(results[0].orig_shape) != (height,width) or results[0].boxes is None:
            raise ValueError("helmet detector must return original-frame axis-aligned boxes")
        detections = []
        for box in results[0].boxes:
            index, conf = float(box.cls[0]), float(box.conf[0])
            if not math.isfinite(index) or not index.is_integer() or not 0 <= index < len(HELMET_CLASSES):
                raise ValueError("helmet detector returned an invalid class ID")
            if not math.isfinite(conf) or not 0 <= conf <= 1:
                raise ValueError("helmet detector returned invalid confidence")
            coords = clipped_box(box.xyxy[0].cpu().numpy(), width, height)
            if coords and conf >= self.confidence:
                detections.append(HelmetDetection(tuple(coords), HELMET_CLASSES[int(index)], conf))
        return detections

    def assessments(self, people, detections):
        people = [(str(key),valid_box(box)) for key,box in people]
        if len({key for key,_ in people}) != len(people):
            raise ValueError("person track IDs must be unique")
        assigned, ambiguous = {key:[] for key,_ in people}, set()
        for detection in detections:
            box = valid_box(detection.bbox_xyxy)
            if detection.class_name not in HELMET_CLASSES or not math.isfinite(detection.confidence) or not 0 <= detection.confidence <= 1:
                raise ValueError("invalid helmet detection")
            candidates = []
            for key,p in people:
                head = (p[0],p[1],p[2],p[1]+.45*(p[3]-p[1]))
                if overlap(box,head)/((box[2]-box[0])*(box[3]-box[1])) >= .8:
                    candidates.append(key)
            if len(candidates) == 1:
                assigned[candidates[0]].append(detection)
            else:
                ambiguous.update(candidates)
        result = {}
        for key,_ in people:
            matches = assigned[key]
            if key in ambiguous or len(matches) > 1:
                result[key] = HelmetAssessment("uncertain",None,"ambiguous_head_association")
            elif not matches:
                result[key] = HelmetAssessment(None,None,"head_not_observed")
            else:
                match = matches[0]; x1,y1,x2,y2 = match.bbox_xyxy
                reason = "small_head" if min(x2-x1,y2-y1) < self.min_head_pixels else "low_confidence" if match.confidence < self.association_confidence else "prediction"
                result[key] = HelmetAssessment(match.class_name if reason == "prediction" else "uncertain",match.confidence,reason)
        return result

    def associate(self, people, detections):
        return {key:value.class_name for key,value in self.assessments(people,detections).items()}

    def associate_riders(self, people, motorcycles, detections):
        """Experimental two-way overlap gate. Crowded/pillion ambiguity abstains.

        The main detector supplies persons AND motorcycles. Labels belong to
        person track IDs. Geometry cannot prove riding; validate in the field.
        """
        people = [(str(key),valid_box(box)) for key,box in people]
        bikes = [(str(key),valid_box(box)) for key,box in motorcycles]
        if len({key for key,_ in bikes}) != len(bikes):
            raise ValueError("motorcycle track IDs must be unique")
        matches, reverse = {}, {}
        for key,p in people:
            lower = (p[0],p[1]+.55*(p[3]-p[1]),p[2],p[3]); candidates = []
            for bike_id,b in bikes:
                horizontal = max(0.,min(p[2],b[2])-max(p[0],b[0]))
                if (horizontal/min(p[2]-p[0],b[2]-b[0]) >= .6
                    and p[0]-.25*(p[2]-p[0]) <= (b[0]+b[2])/2 <= p[2]+.25*(p[2]-p[0])
                    and p[1]+.25*(p[3]-p[1]) < b[1]+.35*(b[3]-b[1])
                    and overlap(lower,b)/((lower[2]-lower[0])*(lower[3]-lower[1])) >= .15):
                    candidates.append(bike_id); reverse.setdefault(bike_id,[]).append(key)
            matches[key] = candidates
        heads = self.assessments(people,detections); result = {}
        for key,candidates in matches.items():
            if not candidates:
                continue
            if len(candidates) != 1 or len(reverse[candidates[0]]) != 1:
                result[key] = HelmetAssessment("uncertain",None,"ambiguous_rider_association")
            else:
                h = heads[key]
                result[key] = HelmetAssessment(h.class_name,h.confidence,h.reason,candidates[0])
        return result


class HelmetReviewConfirmer:
    """Consecutive consistent observations produce pending review, never violation."""
    def __init__(self, duration_s=1., min_observations=5, max_gap_s=.5):
        if not all(math.isfinite(v) and v > 0 for v in (duration_s,max_gap_s)) or isinstance(min_observations,bool) or int(min_observations) != min_observations or min_observations < 2:
            raise ValueError("helmet duration/gap must be positive and at least two observations are required")
        self.duration_s,self.min_observations,self.max_gap_s = duration_s,min_observations,max_gap_s
        self.history = {}

    def clear(self, track_id):
        self.history.pop(str(track_id),None)

    def update(self, track_id, assessment, timestamp_s, frame):
        key,now = str(track_id),float(timestamp_s)
        if not key or not math.isfinite(now) or now < 0 or not isinstance(frame,int) or frame < 0:
            raise ValueError("helmet review requires a track, nonnegative timestamp and frame")
        if not assessment or assessment.class_name not in HELMET_CLASSES or assessment.reason != "prediction" or not assessment.motorcycle_track_id:
            self.clear(key); return None
        if assessment.confidence is None or not math.isfinite(assessment.confidence) or not 0 <= assessment.confidence <= 1:
            raise ValueError("helmet review prediction needs valid confidence")
        signature = (assessment.class_name,assessment.motorcycle_track_id); old = self.history.get(key)
        if not old or old["signature"] != signature or not 0 < now-old["last"] <= self.max_gap_s:
            old = {"signature":signature,"first":now,"last":now,"count":0,"confidence":assessment.confidence,"emitted":False}
            self.history[key] = old
        old.update(last=now,count=old["count"]+1,confidence=min(old["confidence"],assessment.confidence))
        if old["emitted"] or old["count"] < self.min_observations or now-old["first"]+1e-9 < self.duration_s:
            return None
        old["emitted"] = True
        return {"event_type":"helmet_review","track_id":key,"motorcycle_track_id":assessment.motorcycle_track_id,
                "timestamp_s":now,"frame":frame,"helmet_class":assessment.class_name,"confidence":old["confidence"],
                "first_observed_s":old["first"],"confirmed_duration_s":now-old["first"],"observations":old["count"],
                "review_status":"pending","review_required":True,"experimental":True,
                "description":"Temporally consistent helmet prediction on an experimental rider association; inspect footage. Not a confirmed violation."}
