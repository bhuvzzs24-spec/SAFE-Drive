from datetime import datetime,timedelta,timezone
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.demo_admin import cleanup
from safe_drive.storage import SQLiteStore


class RetentionTests(unittest.TestCase):
    def test_cleanup_is_dry_run_by_default_and_deletes_only_old_terminal_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            store=SQLiteStore(root/"demo.sqlite3")
            old,running="a"*32,"b"*32
            for identifier in (old,running):
                store.create_session(identifier,"test","uploaded_video","fixture","model","missing")
                (root/identifier).mkdir()
                (root/identifier/"input.mp4").write_bytes(b"test")
            store.update_session(old,"completed")
            store.update_session(running,"running")
            store.insert_event(old,{"event_id":"old-event","event_type":"review"})
            with closing(sqlite3.connect(store.path)) as conn, conn:
                conn.execute("UPDATE analysis_sessions SET completed_at=? WHERE session_id=?",
                             ((datetime.now(timezone.utc)-timedelta(days=5)).isoformat(),old))
            self.assertEqual(cleanup(root,store.path,72)["eligible_sessions"],[old])
            self.assertTrue((root/old).exists())
            cleanup(root,store.path,72,apply=True)
            self.assertFalse((root/old).exists())
            self.assertIsNone(store.get_session(old))
            self.assertEqual(store.list_events(old),[])
            self.assertTrue((root/running).exists())
            self.assertIsNotNone(store.get_session(running))

    def test_cleanup_refuses_database_outside_managed_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"managed").mkdir()
            SQLiteStore(root/"outside.sqlite3")
            with self.assertRaises(ValueError):
                cleanup(root/"managed",root/"outside.sqlite3",72,apply=True)
