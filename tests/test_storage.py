import tempfile
import unittest
from pathlib import Path

from safe_drive.storage import SQLiteStore


class SQLiteStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.temp_dir.name) / "safe_drive.sqlite3")
        self.store.create_session("s1", "gate-1", "uploaded_video", "clip.mp4", "yolo.pt", "calibrated")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_session_and_track_persist_and_read(self):
        summary = {"unique_track_ids": 1, "tracks": [{
            "track_id": "1", "vehicle_class": "car", "first_seen_s": 0.0, "last_seen_s": 1.0,
            "bbox_xyxy": [0, 0, 10, 10], "trajectory": [[5, 5]], "confidence": 0.9,
            "speed_kmh": 30.0, "speed_quality": "calibrated_estimate", "observations": 2, "active": False
        }]}
        self.store.save_tracks("s1", summary)
        self.store.update_session("s1", "completed", 30, summary)
        session = self.store.list_sessions()[0]
        self.assertEqual(session["session_id"], "s1")
        self.assertEqual(session["summary"]["unique_track_ids"], 1)
        self.assertEqual(session["frames_processed"], 30)

    def test_event_insert_is_idempotent_and_review_is_persisted(self):
        event = {"event_id": "event-1", "event_type": "speed_limit_exceeded", "camera_id": "gate-1",
                 "track_id": "9", "timestamp_s": 2.5, "speed_kmh": 70,
                 "speed_limit_kmh": 50, "review_status": "pending"}
        self.assertTrue(self.store.insert_event("s1", event))
        self.assertFalse(self.store.insert_event("s1", event))
        self.store.review_event("event-1", "verified", "Reviewer")
        loaded = self.store.list_events("s1")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["review_status"], "verified")
        self.assertEqual(loaded[0]["reviewer"], "Reviewer")

    def test_rejects_review_for_unknown_event(self):
        with self.assertRaises(KeyError):
            self.store.review_event("missing", "verified", "Reviewer")


if __name__ == "__main__":
    unittest.main()
