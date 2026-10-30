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

    def test_frontend_assets_and_object_url_preview_policy(self):
        for filename, expected in (("app.css", "text/css"), ("workspace.css", "text/css"),
                                   ("app.js", "javascript"), ("ui-core.js", "javascript"),
                                   ("theme.js", "javascript")):
            with self.subTest(filename=filename):
                response = self.client.get(f"/static/{filename}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.mimetype)
                response.close()
        policy = self.client.get("/").headers["Content-Security-Policy"]
        self.assertIn("media-src 'self' blob:", policy)
        self.assertIn("script-src 'self'", policy)

    def test_saved_session_contract_preserves_missing_measurements_and_review(self):
        # Synthetic storage fixture: this test does not exercise AI inference.
        session_id = "b" * 32
        store = self.dashboard.STORE
        store.create_session(session_id, "test-camera", "uploaded_video", "fixture.mp4", "not-loaded.pt", "missing")
        store.save_tracks(session_id, {"tracks": [{
            "track_id": "4", "vehicle_class": "pedestrian", "first_seen_s": 0, "last_seen_s": 2,
            "bbox_xyxy": [1, 2, 20, 40], "trajectory": [[10, 20]], "confidence": 0.8,
            "speed_kmh": None, "speed_quality": "uncalibrated", "observations": 3, "active": False,
        }]})
        store.insert_event(session_id, {"event_id": "contract-event", "event_type": "approach_risk_screen",
            "timestamp_s": 1.5, "frame": 15, "encounter": {"track_a": "4", "track_b": "8", "risk": "high"}})
        store.review_event("contract-event", "rejected", "Test reviewer")
        store.update_session(session_id, "completed", 20)
        sessions = self.client.get("/api/sessions").get_json()["sessions"]
        self.assertEqual(sessions[0]["calibration_status"], "missing")
        tracks = self.client.get(f"/api/sessions/{session_id}/tracks").get_json()["tracks"]
        self.assertEqual(tracks[0]["object_class"], "pedestrian")
        self.assertIsNone(tracks[0]["speed_kmh"])
        events = self.client.get(f"/api/sessions/{session_id}/events").get_json()["events"]
        self.assertEqual(events[0]["encounter"]["track_a"], "4")
        self.assertEqual(events[0]["review_status"], "rejected")
        self.assertEqual(events[0]["reviewer"], "Test reviewer")


    def test_selected_session_analytics_and_model_readiness_are_honest(self):
        store=self.dashboard.STORE
        for key,frames in [('a'*32,12),('b'*32,35)]:
            store.create_session(key,'synthetic','uploaded_video','fixture','missing.pt','missing')
            store.update_session(key,'completed',frames)
        one=self.client.get('/api/analytics?session_id='+'a'*32)
        self.assertEqual(one.status_code,200);self.assertEqual(one.get_json()['sessions'],1)
        self.assertEqual(one.get_json()['frames_processed'],12)
        self.assertEqual(self.client.get('/api/analytics').get_json()['frames_processed'],47)
        self.assertEqual(self.client.get('/api/analytics?session_id=../bad').status_code,404)
        text=self.client.get('/').get_data(as_text=True)
        self.assertIn(str(store.path.resolve()),text)
        self.assertIn('Model loaded',text);self.assertIn('Not verified',text)

    def test_actual_missing_weight_failure_is_saved_and_recovered_without_inference(self):
        import io,time
        response=self.client.post('/api/jobs',data={'video':(io.BytesIO(b'\0\0\0\x18ftypisom'),'HEADER-ONLY-synthetic.mp4'),
            'model':str(Path(self.temp_dir.name)/'absent.pt')},headers={'X-CSRF-Token':self.csrf})
        self.assertEqual(response.status_code,202);job=response.get_json()['id']
        for _ in range(100):
            state=self.client.get('/api/jobs/'+job).get_json()
            if state['status']=='failed':break
            time.sleep(.01)
        self.assertEqual(state['status'],'failed');self.assertIn('weights',state['error'])
        self.assertNotIn(self.temp_dir.name,state['error'])
        reopened=self.dashboard.SQLiteStore(self.dashboard.STORE.path)
        self.assertEqual(reopened.get_session(job)['status'],'failed')
        self.assertEqual(reopened.list_tracks(job),[])

    def test_private_camera_rejects_calibration_from_another_camera(self):
        import io,json,os
        from unittest.mock import patch
        from safe_drive.camera_input import CameraSource
        app=self.dashboard.create_app({'DEMO_CAMERAS':True});client=app.test_client()
        csrf=re.search(rb'name="csrf-token" content="([^"]+)"',client.get('/').data).group(1).decode()
        geometry={'camera_id':'different','image_points_px':[[0,0],[100,0],[100,100],[0,100]],'road_points_m':[[0,0],[10,0],[10,10],[0,10]]}
        with patch.object(self.dashboard,'load_camera_source',return_value=CameraSource('rtsp','registered','rtsp://10.0.0.2/stream')),patch.dict(os.environ,{'SAFE_DRIVE_CAMERA_ALLOWED_IPS':'10.0.0.2'}):
            response=client.post('/api/camera-jobs',data={'calibration':(io.BytesIO(json.dumps(geometry).encode()),'calibration.json')},headers={'X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,400);self.assertIn('camera_id',response.get_json()['error'])


if __name__ == "__main__":
    unittest.main()
