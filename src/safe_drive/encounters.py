"""Pairwise approach-risk analysis in calibrated road-plane coordinates."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class Encounter:
    track_a: str
    track_b: str
    ttc_s: float | None
    closest_approach_s: float
    closest_distance_m: float
    closing_speed_mps: float
    risk: str


def analyse_pair(track_a: str, track_b: str, pos_a: Sequence[float], vel_a: Sequence[float],
                 pos_b: Sequence[float], vel_b: Sequence[float], horizon_s: float = 5.0,
                 ttc_threshold_s: float = 1.5, distance_threshold_m: float = 2.0) -> Encounter:
    """Estimate closest approach assuming locally constant 2-D velocity.

    This is a screening signal, not a collision prediction: detector noise,
    turning, occlusion, and road topology are not represented.
    """
    if not all(math.isfinite(v) and v > 0 for v in (horizon_s, ttc_threshold_s, distance_threshold_m)):
        raise ValueError("screening horizon and thresholds must be positive and finite")
    for vector in (pos_a, vel_a, pos_b, vel_b):
        if np.asarray(vector).shape != (2,):
            raise ValueError("positions and velocities must be finite 2-D vectors")
    r = np.asarray(pos_b, dtype=float) - np.asarray(pos_a, dtype=float)
    v = np.asarray(vel_b, dtype=float) - np.asarray(vel_a, dtype=float)
    if r.shape != (2,) or v.shape != (2,) or not np.isfinite([*r, *v]).all():
        raise ValueError("positions and velocities must be finite 2-D vectors")
    vv = float(v @ v)
    closing = max(0.0, -float(r @ v) / max(float(np.linalg.norm(r)), 1e-9))
    t_closest = min(horizon_s, max(0.0, -float(r @ v) / vv)) if vv > 1e-9 else horizon_s
    distance = float(np.linalg.norm(r + v * t_closest))
    radial_closing = float(r @ v) < 0
    ttc = float(np.linalg.norm(r)) / closing if radial_closing and closing > 1e-6 else None
    if ttc is not None and ttc <= ttc_threshold_s and distance <= distance_threshold_m:
        risk = "high"
    elif radial_closing and 0 < t_closest < horizon_s and distance <= distance_threshold_m * 2:
        risk = "elevated"
    else:
        risk = "low"
    return Encounter(str(track_a), str(track_b), None if ttc is None else round(ttc, 3),
                     round(t_closest, 3), round(distance, 3), round(closing, 3), risk)
