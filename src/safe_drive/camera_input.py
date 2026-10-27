"""Resolve explicit demo, local-video, webcam, and RTSP camera sources.

Configuration only identifies the requested source. It does not mean that a
camera is online; connection status is established by the capture worker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


class CameraConfigurationError(ValueError):
    """Raised for a malformed or unsupported camera configuration."""


@dataclass(frozen=True)
class CameraSource:
    mode: str
    camera_id: str = "demo"
    source: str | int | None = field(default=None, repr=False)

    @property
    def configured(self) -> bool:
        return self.mode in {"local_video", "webcam", "rtsp"} and self.source is not None

    @property
    def status_label(self) -> str:
        if self.mode == "demo":
            return "DEMO / UPLOAD MODE"
        return f"{self.mode.upper()} SOURCE CONFIGURED"


def resolve_camera_source(mode: str, source: str | int | None = None,
                          camera_id: str = "camera") -> CameraSource:
    """Validate and normalize one source selection without opening it."""
    if not isinstance(mode, str):
        raise CameraConfigurationError("Source mode must be text.")
    mode = mode.strip().lower()
    camera_id = str(camera_id or "camera").strip()[:80] or "camera"
    if mode == "demo":
        return CameraSource("demo", camera_id="demo")
    if mode == "webcam":
        try:
            device = int(source)  # device index, e.g. 0
        except (TypeError, ValueError) as exc:
            raise CameraConfigurationError("Webcam mode needs a numeric device index.") from exc
        if device < 0:
            raise CameraConfigurationError("Webcam device index must be zero or greater.")
        return CameraSource("webcam", camera_id=camera_id, source=device)
    if mode == "local_video":
        if not isinstance(source, (str, os.PathLike)) or not str(source).strip():
            raise CameraConfigurationError("Local-video mode needs a video path.")
        return CameraSource("local_video", camera_id=camera_id, source=str(source))
    if mode == "rtsp":
        if not isinstance(source, str):
            raise CameraConfigurationError("RTSP mode needs a stream URL.")
        parsed = urlsplit(source.strip())
        if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname:
            raise CameraConfigurationError("Camera URL must use rtsp:// or rtsps:// and include a host.")
        return CameraSource("rtsp", camera_id=camera_id, source=source.strip())
    raise CameraConfigurationError("Source mode must be demo, local_video, webcam, or rtsp.")


def load_camera_source(config_path: str | Path | None = None,
                       environ: Mapping[str, str] | None = None) -> CameraSource:
    """Load defaults from JSON, with environment variables taking precedence.

    SAFE_DRIVE_CAMERA_URL overrides the JSON source and is never included in
    repr/status text. If no camera is configured, return explicit demo mode.
    """
    env = os.environ if environ is None else environ
    config: dict = {}
    path = Path(config_path) if config_path is not None else None
    if path and path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CameraConfigurationError("Camera config file is unreadable or invalid JSON.") from exc
        if not isinstance(config, dict):
            raise CameraConfigurationError("Camera config must contain a JSON object.")

    camera_id = env.get("SAFE_DRIVE_CAMERA_ID", config.get("camera_id", "camera"))
    url = env.get("SAFE_DRIVE_CAMERA_URL", "").strip()
    if url:
        return resolve_camera_source("rtsp", url, camera_id)

    mode = env.get("SAFE_DRIVE_CAMERA_MODE", config.get("mode", "demo"))
    if isinstance(mode, str):
        mode = mode.strip().lower()
    if mode == "demo":
        demo_video = config.get("demo_video")
        if demo_video:
            return resolve_camera_source("local_video", demo_video, camera_id)
        return resolve_camera_source("demo")
    if mode == "rtsp":
        return resolve_camera_source("rtsp", config.get("stream_url"), camera_id)
    if mode == "webcam":
        return resolve_camera_source("webcam", env.get("SAFE_DRIVE_WEBCAM_INDEX", config.get("device_index", 0)), camera_id)
    if mode == "local_video":
        return resolve_camera_source("local_video", config.get("video_path"), camera_id)
    raise CameraConfigurationError("Configured camera mode is unsupported.")
