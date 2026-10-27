"""Transparent advisory risk score; weights and thresholds are configurable."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskPolicy:
    speed_limit_kmh: float = 50.0
    speed_weight: float = 40.0
    helmet_weight: float = 30.0
    near_miss_weight: float = 30.0
    max_score: float = 100.0


def score_event(speed_kmh: float | None, speed_valid: bool, helmet_violation: bool | None,
                near_miss: bool, policy: RiskPolicy = RiskPolicy()) -> dict:
    """Return a normalized research score and explicit evidence/quality flags.

    No fine, identity inference, or enforcement action is generated. Missing
    signals contribute zero and are listed as missing rather than treated safe.
    """
    components = {}
    missing = []
    if speed_valid and speed_kmh is not None:
        excess = max(0.0, speed_kmh / max(policy.speed_limit_kmh, 1e-9) - 1.0)
        components["speed"] = min(policy.speed_weight, policy.speed_weight * excess)
    else:
        components["speed"] = 0.0
        missing.append("speed")
    if helmet_violation is None:
        components["helmet"] = 0.0
        missing.append("helmet")
    else:
        components["helmet"] = policy.helmet_weight if helmet_violation else 0.0
    components["near_miss"] = policy.near_miss_weight if near_miss else 0.0
    score = min(policy.max_score, sum(components.values()))
    level = "low" if score < 25 else "moderate" if score < 55 else "high"
    return {"score": round(score, 2), "level": level, "components": components,
            "missing_signals": missing, "use": "advisory_research_only"}
