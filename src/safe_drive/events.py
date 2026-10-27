"""Append-only JSONL research event writer with stable event identifiers."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON event value: {type(value).__name__}")


def write_event(path: str | Path, event: dict[str, Any]) -> str:
    """Append one event and return its SHA-256 event id (content-addressed)."""
    payload = {"schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(), **event}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_jsonable)
    event_id = hashlib.sha256(canonical.encode()).hexdigest()
    payload["event_id"] = event_id
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True, default=_jsonable) + "\n")
    return event_id
