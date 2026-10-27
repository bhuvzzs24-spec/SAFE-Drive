"""Timestamp-aware speed estimation from calibrated ground-plane positions."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import math
from statistics import median


@dataclass(frozen=True)
class SpeedEstimate:
    speed_kmh: float | None
    quality: str
    elapsed_s: float


class SpeedEstimator:
    def __init__(self, window_s: float = 1.0, min_baseline_s: float = 0.25,
                 max_baseline_s: float = 2.0, max_points: int = 64,
                 smoothing_points: int = 5, max_speed_kmh: float = 250.0):
        if not 0 < min_baseline_s <= window_s <= max_baseline_s:
            raise ValueError("require 0 < min_baseline_s <= window_s <= max_baseline_s")
        if smoothing_points < 1 or max_speed_kmh <= 0:
            raise ValueError("smoothing_points and max_speed_kmh must be positive")
        self.window_s = window_s
        self.min_baseline_s = min_baseline_s
        self.max_baseline_s = max_baseline_s
        self.history = defaultdict(lambda: deque(maxlen=max_points))
        self.speed_history = defaultdict(lambda: deque(maxlen=smoothing_points))
        self.max_speed_kmh = float(max_speed_kmh)

    def update(self, track_id: str | int, x_m: float, y_m: float, timestamp_s: float) -> SpeedEstimate:
        if not all(math.isfinite(v) for v in (x_m, y_m, timestamp_s)):
            raise ValueError("position and timestamp must be finite")
        hist = self.history[track_id]
        if hist and timestamp_s <= hist[-1][0]:
            # A timestamp reset means a new clip/track segment, never a negative speed.
            hist.clear()
        hist.append((timestamp_s, x_m, y_m))
        if len(hist) < 2:
            return SpeedEstimate(None, "warming_up", 0.0)
        now = hist[-1][0]
        candidates = [p for p in hist if self.min_baseline_s <= now - p[0] <= self.max_baseline_s]
        if not candidates:
            return SpeedEstimate(None, "warming_up", 0.0)
        old = min(candidates, key=lambda p: abs((now - p[0]) - self.window_s))
        dt = now - old[0]
        speed = math.hypot(hist[-1][1] - old[1], hist[-1][2] - old[2]) / dt * 3.6
        if speed > self.max_speed_kmh:
            return SpeedEstimate(None, "implausible_speed_rejected", dt)
        self.speed_history[track_id].append(speed)
        return SpeedEstimate(round(median(self.speed_history[track_id]), 2), "calibrated_estimate", dt)

    def clear(self, track_id: str | int) -> None:
        self.history.pop(track_id, None)
        self.speed_history.pop(track_id, None)
