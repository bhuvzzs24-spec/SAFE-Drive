import json
from pathlib import Path
import tempfile
import unittest

from safe_drive.camera_input import (
    CameraConfigurationError,
    load_camera_source,
    resolve_camera_source,
)


class CameraInputTests(unittest.TestCase):
    def test_missing_configuration_is_explicit_demo_mode(self):
        source = load_camera_source("does-not-exist.json", environ={})
        self.assertEqual(source.mode, "demo")
        self.assertFalse(source.configured)
        self.assertEqual(source.status_label, "DEMO / UPLOAD MODE")

    def test_environment_rtsp_overrides_json_without_exposing_url_in_repr(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "camera.json"
            path.write_text(json.dumps({"mode": "demo"}), encoding="utf-8")
            secret_url = "rtsp://researcher:private-pass@192.168.1.20:554/live"
            source = load_camera_source(path, environ={"SAFE_DRIVE_CAMERA_URL": secret_url,
                                                       "SAFE_DRIVE_CAMERA_ID": "north-gate"})
        self.assertEqual(source.mode, "rtsp")
        self.assertTrue(source.configured)
        self.assertEqual(source.camera_id, "north-gate")
        self.assertNotIn("private-pass", repr(source))

    def test_configured_webcam_index_is_normalized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "camera.json"
            path.write_text(json.dumps({"mode": "webcam", "device_index": "2"}), encoding="utf-8")
            source = load_camera_source(path, environ={})
        self.assertEqual(source.mode, "webcam")
        self.assertEqual(source.source, 2)

    def test_rejects_non_rtsp_camera_urls(self):
        with self.assertRaises(CameraConfigurationError):
            resolve_camera_source("rtsp", "https://camera.example/stream")

    def test_rejects_negative_webcam_index(self):
        with self.assertRaises(CameraConfigurationError):
            resolve_camera_source("webcam", -1)


if __name__ == "__main__":
    unittest.main()
