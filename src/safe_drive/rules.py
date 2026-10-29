"""Temporal speed-limit confirmation and per-track event deduplication."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SpeedLimitRule:
    limit_kmh: float | None
    tolerance_kmh: float = 0.0
    confirmation_s: float = 1.0
    cooldown_s: float = 30.0

    def __post_init__(self):
        if self.limit_kmh is not None and (not math.isfinite(self.limit_kmh) or self.limit_kmh <= 0):
            raise ValueError("speed limit must be a positive finite number or None")
        if not math.isfinite(self.tolerance_kmh) or self.tolerance_kmh < 0:
            raise ValueError("speed tolerance must be finite and non-negative")
        if not math.isfinite(self.confirmation_s) or self.confirmation_s < 0:
            raise ValueError("confirmation duration must be finite and non-negative")
        if not math.isfinite(self.cooldown_s) or self.cooldown_s < 0:
            raise ValueError("event cooldown must be finite and non-negative")


class SpeedViolationConfirmer:
    """Emit one event after a valid per-track exceedance persists long enough."""

    def __init__(self, rule: SpeedLimitRule, max_observation_gap_s: float = 2.0):
        if max_observation_gap_s <= 0:
            raise ValueError("max observation gap must be positive")
        self.rule = rule
        self.max_observation_gap_s = float(max_observation_gap_s)
        self._states: dict[str, dict] = {}
        self._last_event_s: dict[str, float] = {}
        self._last_observation_s: dict[str, float] = {}

    def update(self, track_id: str | int, speed_kmh: float | None, timestamp_s: float,
               speed_quality: str, confidence: float | None = None) -> dict | None:
        if self.rule.limit_kmh is None:
            return None
        if not math.isfinite(timestamp_s):
            raise ValueError("timestamp must be finite")
        key = str(track_id)
        last = self._last_observation_s.get(key)
        if last is not None and timestamp_s <= last:
            self.clear(key)
            self._last_event_s.pop(key, None)
        self._last_observation_s[key] = timestamp_s
        state = self._states.get(key)
        valid = speed_kmh is not None and speed_quality == "calibrated_estimate" and math.isfinite(speed_kmh)
        if not valid:
            # Missing evidence cannot count toward continuous exceedance time.
            self._states.pop(key, None)
            return None

        threshold = self.rule.limit_kmh + self.rule.tolerance_kmh
        if speed_kmh <= threshold:
            self._states.pop(key, None)
            return None

        if state is None or timestamp_s - state["last_seen_s"] > self.max_observation_gap_s:
            previous_event_s = self._last_event_s.get(key, -math.inf)
            state = {"start_s": timestamp_s, "last_seen_s": timestamp_s,
                     "last_event_s": previous_event_s, "emitted": False}
            self._states[key] = state
        else:
            state["last_seen_s"] = timestamp_s

        duration = timestamp_s - state["start_s"]
        if (not state["emitted"] and duration >= self.rule.confirmation_s and
                timestamp_s - state["last_event_s"] >= self.rule.cooldown_s):
            state["emitted"] = True
            state["last_event_s"] = timestamp_s
            self._last_event_s[key] = timestamp_s
            return {
                "event_type": "speed_limit_exceeded",
                "track_id": key,
                "timestamp_s": round(timestamp_s, 3),
                "speed_kmh": round(float(speed_kmh), 2),
                "speed_limit_kmh": self.rule.limit_kmh,
                "tolerance_kmh": self.rule.tolerance_kmh,
                "confirmed_duration_s": round(duration, 3),
                "speed_quality": speed_quality,
                "confidence": confidence,
                "review_status": "pending",
            }
        return None

    def clear(self, track_id: str | int) -> None:
        self._states.pop(str(track_id), None)
        self._last_observation_s.pop(str(track_id), None)
