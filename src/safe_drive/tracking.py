"""Per-track measurement history independent of the detector/tracker library."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import math


@dataclass
class TrackRecord:
    track_id: str
    vehicle_class: str
    first_seen_s: float
    last_seen_s: float
    bbox_xyxy: list[float]
    confidence: float | None
    speed_kmh: float | None
    speed_quality: str
    helmet_class: str | None = None
    observations: int = 0
    active: bool = True
    trajectory: deque = field(default_factory=deque, repr=False)

    def as_dict(self) -> dict:
        result = asdict(self)
        result["trajectory"] = list(self.trajectory)
        result["last_duration_s"] = max(0.0, self.last_seen_s - self.first_seen_s)
        return result


class TrackRegistry:
    """Retain independent histories and expire tracks after a time gap."""

    def __init__(self, max_idle_seconds: float = 2.0, trail_length: int = 40):
        if max_idle_seconds <= 0 or trail_length < 2:
            raise ValueError("max_idle_seconds must be positive and trail_length at least two")
        self.max_idle_seconds = float(max_idle_seconds)
        self.trail_length = int(trail_length)
        self.records: dict[str, TrackRecord] = {}

    def observe(self, track_id: str | int, timestamp_s: float, bbox_xyxy,
                vehicle_class: str, confidence: float | None,
                speed_kmh: float | None = None,
                speed_quality: str = "uncalibrated",
                helmet_class: str | None = None) -> TrackRecord:
        timestamp_s = float(timestamp_s)
        bbox = [float(value) for value in bbox_xyxy]
        if len(bbox) != 4 or not all(math.isfinite(v) for v in [timestamp_s, *bbox]):
            raise ValueError("timestamp and four bounding-box coordinates must be finite")
        if bbox[2] < bbox[0] or bbox[3] < bbox[1]:
            raise ValueError("bounding box coordinates are reversed")
        if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("detection confidence must be between zero and one")
        key = str(track_id)
        rec = self.records.get(key)
        if rec is None:
            rec = TrackRecord(key, str(vehicle_class), timestamp_s, timestamp_s, bbox,
                              confidence, speed_kmh, speed_quality,
                              trajectory=deque(maxlen=self.trail_length))
            self.records[key] = rec
        if timestamp_s < rec.last_seen_s:
            raise ValueError("track timestamps must be monotonic")
        rec.vehicle_class = str(vehicle_class)
        rec.last_seen_s = timestamp_s
        rec.bbox_xyxy = bbox
        rec.confidence = confidence
        rec.speed_kmh = speed_kmh if speed_kmh is not None and math.isfinite(speed_kmh) else None
        rec.speed_quality = speed_quality if rec.speed_kmh is not None else "uncalibrated"
        rec.helmet_class = helmet_class
        rec.active = True
        rec.observations += 1
        rec.trajectory.append(((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2))
        return rec

    def expire(self, now_s: float) -> list[str]:
        expired = []
        for key, rec in self.records.items():
            if rec.active and now_s - rec.last_seen_s > self.max_idle_seconds:
                rec.active = False
                expired.append(key)
        return expired

    def summary(self) -> dict:
        records = list(self.records.values())
        active = [r for r in records if r.active]
        valid_speed = [r for r in records if r.speed_kmh is not None]
        return {
            "unique_track_ids": len(records),
            "active_tracks": len(active),
            "completed_tracks": len(records) - len(active),
            "tracks_with_valid_speed": len(valid_speed),
            "tracks_without_valid_speed": len(records) - len(valid_speed),
            "tracks": [r.as_dict() for r in records],
        }
