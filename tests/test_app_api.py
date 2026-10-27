"""Dashboard API smoke tests (run after installing the base project dependencies)."""
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("flask"), "Flask is not installed in this environment")
class DashboardApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as dashboard
        cls.dashboard = dashboard

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.dashboard.DATA = root
        self.dashboard.STORE = self.dashboard.SQLiteStore(root / "test.sqlite3")
        self.client = self.dashboard.create_app().test_client()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/static/app.css", response.data)
        self.csrf = re.search(rb'name="csrf-token" content="([^"]+)"', response.data).group(1).decode()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_empty_sessions_api_returns_real_empty_database_state(self):
        response = self.client.get("/api/sessions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"sessions": []})

    def test_review_endpoint_persists_decision(self):
        self.dashboard.STORE.create_session("a" * 32, "cam", "uploaded_video", "clip.mp4", "model.pt", "missing")
        self.dashboard.STORE.insert_event("a" * 32, {
            "event_id": "evt-1", "event_type": "approach_risk_screen", "timestamp_s": 1.0,
        })
        response = self.client.post("/api/events/evt-1/review", json={
            "decision": "verified", "reviewer": "QA"
        }, headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.dashboard.STORE.list_events("a" * 32)[0]["review_status"], "verified")

    def test_review_endpoint_rejects_missing_csrf_token(self):
        response = self.client.post("/api/events/missing/review", json={"decision": "verified", "reviewer": "QA"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
