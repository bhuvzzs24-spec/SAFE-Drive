import tempfile
import unittest
from pathlib import Path

from safe_drive.rules import SpeedLimitRule, SpeedViolationConfirmer
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
        self.assertEqual(self.store.list_tracks("s1")[0]["vehicle_class"], "car")

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

    def test_analytics_are_aggregated_from_saved_sessions_tracks_and_reviews(self):
        self.store.insert_event("s1", {"event_id": "evt-analytics", "event_type": "speed_limit_exceeded"})
        self.store.review_event("evt-analytics", "verified", "Reviewer")
        summary = {"tracks": [{"track_id": "1", "vehicle_class": "car", "first_seen_s": 0,
                    "last_seen_s": 1, "bbox_xyxy": [0, 0, 10, 10], "trajectory": [],
                    "confidence": 0.9, "speed_kmh": 30.0,
                    "speed_quality": "calibrated_estimate", "observations": 2, "active": False}]}
        self.store.save_tracks("s1", summary)
        self.store.update_session("s1", "completed", 12, {"source_ended": False})
        analytics = self.store.analytics()
        self.assertEqual(analytics["sessions"], 1)
        self.assertEqual(analytics["completed_sessions"], 1)
        self.assertEqual(analytics["frames_processed"], 12)
        self.assertEqual(analytics["vehicle_tracks"], 1)
        self.assertEqual(analytics["tracks_with_valid_speed"], 1)
        self.assertEqual(analytics["reviewed_events"], 1)

    def test_tracks_pedestrians_events_and_reviews_survive_store_reopen(self):
        summary = {"tracks": [
            {"track_id": "1", "vehicle_class": "car", "first_seen_s": 0, "last_seen_s": 1,
             "bbox_xyxy": [0, 0, 20, 20], "trajectory": [[10, 10]], "confidence": 0.9,
             "speed_kmh": 36, "speed_quality": "calibrated_estimate", "observations": 2, "active": False},
            {"track_id": "2", "vehicle_class": "pedestrian", "first_seen_s": 0, "last_seen_s": 1,
             "bbox_xyxy": [30, 0, 40, 30], "trajectory": [[35, 15]], "confidence": 0.8,
             "speed_kmh": None, "speed_quality": "uncalibrated", "helmet_class": "half_face_helmet",
             "observations": 2, "active": False},
        ]}
        self.store.save_tracks("s1", summary)
        self.store.update_session("s1", "completed", 25, summary)
        confirmer = SpeedViolationConfirmer(SpeedLimitRule(30, tolerance_kmh=2, confirmation_s=1))
        self.assertIsNone(confirmer.update("1", 36, 0, "calibrated_estimate"))
        event = confirmer.update("1", 36, 1, "calibrated_estimate")
        self.assertIsNotNone(event)
        event["event_id"] = "persisted-event"
        self.store.insert_event("s1", event)
        self.store.review_event("persisted-event", "verified", "Reviewer A")

        reopened = SQLiteStore(self.store.path)
        tracks = reopened.list_tracks("s1")
        self.assertEqual([track["vehicle_class"] for track in tracks], ["car", "pedestrian"])
        self.assertEqual(tracks[1]["helmet_class"], "half_face_helmet")
        self.assertIsNone(tracks[1]["speed_kmh"])
        self.assertEqual(reopened.list_events("s1")[0]["review_status"], "verified")
        self.assertEqual(reopened.list_events("s1")[0]["reviewer"], "Reviewer A")
        self.assertEqual(reopened.get_session("s1")["status"], "completed")
        analytics = reopened.analytics()
        self.assertEqual(analytics["vehicle_tracks"], 1)
        self.assertEqual(analytics["pedestrians"], 1)


if __name__ == "__main__":
    unittest.main()
