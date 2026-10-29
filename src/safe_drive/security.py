"""Fail-closed configuration and small controlled-demo security primitives."""
from collections import deque
from datetime import timedelta
import ipaddress
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit


def deployment_settings():
    production = os.environ.get("SAFE_DRIVE_ENV", "local") == "production"
    secret = os.environ.get("SAFE_DRIVE_SECRET", "")
    hosts = [v.strip().lower() for v in os.environ.get("SAFE_DRIVE_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if v.strip()]
    if production and (len(secret) < 32 or not hosts or any("*" in h or "/" in h or ":" in h for h in hosts)):
        raise ValueError("Production requires SAFE_DRIVE_SECRET (32+ random characters) and exact SAFE_DRIVE_ALLOWED_HOSTS.")
    users = json.loads(os.environ.get("SAFE_DRIVE_USERS_JSON", "{}"))
    if not isinstance(users, dict):
        raise ValueError("SAFE_DRIVE_USERS_JSON must be an object")
    for name, record in users.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name) or not isinstance(record, dict) or record.get("role") not in {"admin","analyst","reviewer"}:
            raise ValueError("Invalid demo user configuration")
        if not isinstance(record.get("password_hash"), str) or not record["password_hash"].startswith(("scrypt:", "pbkdf2:")):
            raise ValueError("Demo passwords must be Werkzeug scrypt/pbkdf2 hashes")
    settings = {"DEMO_PRODUCTION": production, "DEMO_USERS": users,
            "SECRET_KEY": secret or None, "DEMO_HOSTS": hosts,
            "DEMO_ALLOW_UPLOADS": os.environ.get("SAFE_DRIVE_ALLOW_UPLOADS", "0" if production else "1") == "1",
            "DEMO_CAMERAS": not production and os.environ.get("SAFE_DRIVE_ENABLE_CAMERAS", "0") == "1",
            "SESSION_COOKIE_SECURE": production, "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax", "PERMANENT_SESSION_LIFETIME": timedelta(minutes=30),
            "SESSION_REFRESH_EACH_REQUEST": False,
            "MAX_CONTENT_LENGTH": min(int(os.environ.get("SAFE_DRIVE_MAX_UPLOAD", str(30*1024*1024 if production else 300*1024*1024))), 300*1024*1024),
            "MAX_FORM_MEMORY_SIZE": 64*1024, "MAX_FORM_PARTS": 8,
            "DEMO_MAX_JOB_SECONDS": min(int(os.environ.get("SAFE_DRIVE_JOB_TIMEOUT", "120")),600),
            "DEMO_MIN_FREE_BYTES": int(os.environ.get("SAFE_DRIVE_MIN_FREE_BYTES", str(1024**3))),
            "DEMO_MAX_DATA_BYTES": int(os.environ.get("SAFE_DRIVE_MAX_DATA_BYTES", str(5*1024**3))),
            "DEMO_SAMPLE_VIDEO": os.environ.get("SAFE_DRIVE_SAMPLE_VIDEO", ""),
            "DEMO_SAMPLE_LICENSE": os.environ.get("SAFE_DRIVE_SAMPLE_LICENSE", "")}
    if not 1 <= settings["DEMO_MAX_JOB_SECONDS"] <= 600 or settings["MAX_CONTENT_LENGTH"] <= 0 or settings["DEMO_MIN_FREE_BYTES"] < 0 or settings["DEMO_MAX_DATA_BYTES"] <= 0:
        raise ValueError("Upload, storage and worker limits must be positive")
    return settings


class RateGate:
    """One-process bounded global login budget; no trust in forwarded client IPs."""
    def __init__(self, count=20, period=60):
        self.count, self.period, self.times, self.lock = count, period, deque(), threading.Lock()

    def allow(self):
        now = time.monotonic()
        with self.lock:
            while self.times and now-self.times[0] >= self.period:
                self.times.popleft()
            if len(self.times) >= self.count:
                return False
            self.times.append(now)
            return True


def validate_video_header(path, extension):
    with Path(path).open("rb") as source:
        data = source.read(32)
    if extension in {"mp4","mov"}:
        valid = len(data) >= 12 and data[4:8] == b"ftyp"
    elif extension == "avi":
        valid = data[:4] == b"RIFF" and data[8:12] == b"AVI "
    elif extension in {"mkv","webm"}:
        valid = data[:4] == b"\x1a\x45\xdf\xa3"
    else:
        valid = False
    if not valid:
        raise ValueError("File signature does not match an accepted video container. Decoding is checked separately by the bounded worker.")


def confined_file(root, path):
    root, path = Path(root).resolve(), Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("Evidence path is outside the managed storage directory")
    return path.resolve()


def registered_camera_url(source, allowed_ips):
    """Private operators can use a configured IP literal only; no client URLs/DNS.

    Production camera operations are disabled in the HTTP authorization layer.
    Network egress controls must additionally prevent protocol redirects.
    """
    try:
        parsed = urlsplit(source)
        address = ipaddress.ip_address(parsed.hostname or "")
        allowed = {ipaddress.ip_address(v.strip()) for v in allowed_ips.split(",") if v.strip()}
        if parsed.scheme not in {"rtsp","rtsps"} or parsed.port not in {None,554,322} or parsed.fragment:
            raise ValueError()
        if address not in allowed or address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Camera must be a server-configured RTSP IP literal on the explicit allowed-IP list; loopback, metadata/link-local and special addresses are forbidden.") from None
    return source
