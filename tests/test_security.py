import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

from safe_drive.job_runner import supervise_job
from safe_drive.rules import SpeedLimitRule
from safe_drive.security import RateGate, confined_file, deployment_settings, registered_camera_url, validate_video_header


class SecurityPrimitiveTests(unittest.TestCase):
    def test_production_fails_without_secret_and_exact_hosts(self):
        with patch.dict(os.environ,{"SAFE_DRIVE_ENV":"production","SAFE_DRIVE_SECRET":"","SAFE_DRIVE_ALLOWED_HOSTS":"demo.example"}):
            with self.assertRaises(ValueError):
                deployment_settings()
        with patch.dict(os.environ,{"SAFE_DRIVE_ENV":"production","SAFE_DRIVE_SECRET":"x"*40,"SAFE_DRIVE_ALLOWED_HOSTS":"*.example"}):
            with self.assertRaises(ValueError):
                deployment_settings()

    def test_camera_allowlist_rejects_dns_metadata_loopback_and_unregistered_sources(self):
        for source in ("rtsp://localhost/a","rtsp://127.0.0.1/a","rtsp://169.254.169.254/a",
                       "http://10.0.0.2/a","rtsp://10.0.0.3/a","rtsp://10.0.0.2:8000/a","rtsp://[::1]/a"):
            with self.subTest(source=source),self.assertRaises(ValueError):
                registered_camera_url(source,"10.0.0.2,127.0.0.1,169.254.169.254,::1")
        self.assertEqual(registered_camera_url("rtsp://10.0.0.2:554/a","10.0.0.2"),"rtsp://10.0.0.2:554/a")

    def test_container_signature_and_path_symlink_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root/"clip.mp4"
            good.write_bytes(b"\x00\x00\x00\x18ftypisom"+b"\0"*20)
            validate_video_header(good,"mp4")
            with self.assertRaises(ValueError):
                validate_video_header(good,"avi")
            link = root/"alias.mp4"
            link.symlink_to(good)
            with self.assertRaises(ValueError):
                confined_file(root,link)
            with self.assertRaises(ValueError):
                confined_file(root,root/"../secret")

    def test_rate_limit_has_bounded_global_budget(self):
        gate = RateGate(count=2)
        self.assertTrue(gate.allow());self.assertTrue(gate.allow());self.assertFalse(gate.allow())

    def test_supervisor_enforces_deadline_and_removes_sensitive_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            process = Mock(pid=123,returncode=None)
            process.poll.return_value = None
            secret_source = "rtsp://private-user:private-password@10.0.0.2/a"
            with patch("safe_drive.job_runner.subprocess.Popen",return_value=process) as spawn, \
                 patch("safe_drive.job_runner.time.monotonic",side_effect=[0,121]), \
                 patch("safe_drive.job_runner.os.killpg") as kill:
                with self.assertRaisesRegex(TimeoutError,"deadline") as error:
                    supervise_job("a",secret_source,None,"model.pt",folder,folder/"db.sqlite3",Mock(is_set=Mock(return_value=False)),
                                  30,"registered-camera",SpeedLimitRule(None),120,Mock())
                self.assertNotIn(secret_source,str(error.exception))
                self.assertNotIn(secret_source,str(spawn.call_args.args))
                self.assertEqual(spawn.call_args.kwargs["stderr"],-3)
                kill.assert_called_once()
                process.wait.assert_called_once()
            self.assertFalse((folder/"worker.request.json").exists())


@unittest.skipUnless(importlib.util.find_spec("flask"),"Flask is not installed")
class DemoSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        from werkzeug.security import generate_password_hash
        cls.module = app
        cls.password_hash = generate_password_hash("test-only-long-password")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.module.DATA = self.root
        self.module.STORE = self.module.SQLiteStore(self.root/"test.sqlite3")
        self.app = self.module.create_app({"TESTING":True,"DEMO_PRODUCTION":True,"SECRET_KEY":"test-only-key-not-for-production",
            "DEMO_HOSTS":["localhost"],"DEMO_ALLOW_UPLOADS":True,"DEMO_CAMERAS":True,
            "DEMO_MIN_FREE_BYTES":0,"DEMO_MAX_DATA_BYTES":10**9,
            "DEMO_USERS":{role:{"role":role,"password_hash":self.password_hash} for role in ("admin","analyst","reviewer")}})
        self.client = self.app.test_client()
        self.base = "https://localhost"
        home = self.client.get("/",base_url=self.base)
        self.csrf = re.search(rb'name="csrf-token" content="([^"]+)"',home.data).group(1).decode()

    def login(self,role):
        result = self.client.post("/login",base_url=self.base,data={"username":role,"password":"test-only-long-password","csrf_token":self.csrf})
        self.assertEqual(result.status_code,302)
        home = self.client.get("/",base_url=self.base)
        self.csrf = re.search(rb'name="csrf-token" content="([^"]+)"',home.data).group(1).decode()
        return result

    def post(self,path,**kwargs):
        return self.client.post(path,base_url=self.base,headers={"X-CSRF-Token":self.csrf},**kwargs)

    def test_public_health_and_empty_scope_do_not_disclose_private_sessions(self):
        self.module.STORE.create_session("a"*32,"private-camera","rtsp","private-name","private-model","missing")
        self.assertEqual(self.client.get("/healthz",base_url=self.base).get_json(),{"status":"ok"})
        self.assertEqual(self.client.get("/api/sessions",base_url=self.base).get_json(),{"sessions":[]})
        self.assertEqual(self.client.get("/api/analytics",base_url=self.base).get_json()["sessions"],0)
        for path in ("/api/sessions/"+"a"*32+"/video","/api/sessions/"+"a"*32+"/tracks","/api/jobs/"+"a"*32):
            self.assertEqual(self.client.get(path,base_url=self.base).status_code,401)
        self.assertFalse(self.client.get("/api/demo",base_url=self.base).get_json()["available"])

    def test_login_rotates_csrf_and_secure_cookie_logout_revokes_access(self):
        previous = self.csrf
        response = self.login("admin")
        cookie = response.headers["Set-Cookie"]
        for flag in ("Secure","HttpOnly","SameSite=Lax"):
            self.assertIn(flag,cookie)
        self.assertNotEqual(previous,self.csrf)
        self.assertEqual(self.client.post("/api/jobs",base_url=self.base,headers={"X-CSRF-Token":previous}).status_code,403)
        self.assertEqual(self.post("/logout").status_code,302)
        self.assertEqual(self.client.get("/api/jobs/"+"a"*32,base_url=self.base).status_code,401)

    def test_roles_cannot_escalate_and_public_cameras_are_disabled_even_for_admin(self):
        self.login("analyst")
        self.assertEqual(self.post("/api/events/x/review",json={"decision":"verified","reviewer":"spoof"}).status_code,403)
        self.assertEqual(self.post("/api/camera-jobs",data={"stream_url":"rtsp://169.254.169.254/a"}).status_code,403)
        self.post("/logout")
        home=self.client.get("/",base_url=self.base)
        self.csrf=re.search(rb'name="csrf-token" content="([^"]+)"',home.data).group(1).decode()
        self.login("reviewer")
        self.assertEqual(self.post("/api/jobs").status_code,403)

    def test_admin_cannot_enable_cameras_or_override_the_configured_public_model(self):
        self.login("admin")
        self.assertEqual(self.post("/api/camera-jobs",data={"stream_url":"rtsp://private:secret@10.0.0.2/a"}).status_code,403)
        self.app.config["DEMO_ALLOW_UPLOADS"] = False
        self.assertEqual(self.post("/api/jobs").status_code,403)

    def test_password_rotation_revokes_existing_session(self):
        self.login("admin")
        self.app.config["DEMO_USERS"]["admin"]["password_hash"] = "scrypt:rotated-not-a-valid-login"
        self.assertEqual(self.client.get("/api/jobs/"+"a"*32,base_url=self.base).status_code,401)

    def test_review_records_authenticated_reviewer_and_malformed_json_is_rejected(self):
        store = self.module.STORE
        store.create_session("a"*32,"test","uploaded_video","clip","model","missing")
        store.insert_event("a"*32,{"event_id":"evt","event_type":"approach_risk_screen"})
        self.login("reviewer")
        self.assertEqual(self.post("/api/events/evt/review",json=["invalid"]).status_code,400)
        self.assertEqual(self.post("/api/events/evt/review",json={"decision":"verified","reviewer":"spoof"}).status_code,200)
        self.assertEqual(store.list_events("a"*32)[0]["reviewer"],"reviewer")

    def test_upload_rejects_disguised_files_arbitrary_models_and_oversize_requests(self):
        self.login("admin")
        for data in ({"video":(io.BytesIO(b"not a video"),"../../evil.mp4")},
                     {"video":(io.BytesIO(b"\0\0\0\x18ftypisom"),"clip.mp4"),"model":"/etc/passwd"}):
            self.assertEqual(self.post("/api/jobs",data=data).status_code,400)
        self.assertFalse(any(path.is_dir() for path in self.root.iterdir()))
        self.app.config["MAX_CONTENT_LENGTH"]=64
        self.assertEqual(self.post("/api/jobs",data={"video":(io.BytesIO(b"x"*1000),"clip.mp4")}).status_code,413)

    def test_queue_is_bounded_and_server_generated_paths_ignore_upload_name(self):
        self.login("admin")
        with patch.object(self.module.WORKERS,"submit"):
            for _ in range(2):
                result=self.post("/api/jobs",data={"video":(io.BytesIO(b"\0\0\0\x18ftypisom"),"../../clip.mp4")})
                self.assertEqual(result.status_code,202)
                identifier=result.get_json()["id"]
                self.assertTrue((self.root/identifier/"input.mp4").is_file())
            result=self.post("/api/jobs",data={"video":(io.BytesIO(b"\0\0\0\x18ftypisom"),"clip.mp4")})
            self.assertEqual(result.status_code,429)

    def test_host_https_csrf_and_public_upload_denial(self):
        self.assertEqual(self.client.get("/healthz",base_url="https://untrusted.example").status_code,403)
        self.assertEqual(self.client.post("/login",base_url="http://localhost",data={}).status_code,403)
        self.assertEqual(self.client.post("/login",base_url=self.base,data={}).status_code,403)
        self.assertEqual(self.post("/api/jobs").status_code,401)

    def test_restart_marks_interrupted_jobs_failed_without_retry(self):
        store=self.module.STORE
        store.create_session("a"*32,"test","rtsp","camera","model","missing")
        store.update_session("a"*32,"running")
        self.assertEqual(store.recover_interrupted_sessions(),1)
        self.assertEqual(store.get_session("a"*32)["status"],"failed")
        self.assertEqual(store.recover_interrupted_sessions(),0)
