"""Small SQLite repository for sessions, track summaries, events and reviews."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


def _json_default(value: Any):
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cameras (
                    camera_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    source_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS calibrations (
                    calibration_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS speed_rules (
                    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
                    road_segment TEXT NOT NULL DEFAULT '',
                    lane_id TEXT NOT NULL DEFAULT '',
                    speed_limit_kmh REAL NOT NULL CHECK(speed_limit_kmh > 0),
                    tolerance_kmh REAL NOT NULL DEFAULT 0 CHECK(tolerance_kmh >= 0),
                    confirmation_s REAL NOT NULL DEFAULT 1 CHECK(confirmation_s >= 0),
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS analysis_sessions (
                    session_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    source_mode TEXT NOT NULL,
                    input_name TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    calibration_status TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    frames_processed INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_started ON analysis_sessions(started_at DESC);
                CREATE TABLE IF NOT EXISTS vehicle_tracks (
                    session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id) ON DELETE CASCADE,
                    track_id TEXT NOT NULL,
                    vehicle_class TEXT NOT NULL,
                    first_seen_s REAL NOT NULL,
                    last_seen_s REAL NOT NULL,
                    bbox_json TEXT NOT NULL,
                    trajectory_json TEXT NOT NULL,
                    confidence REAL,
                    speed_kmh REAL,
                    speed_quality TEXT NOT NULL,
                    observations INTEGER NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0, 1)),
                    PRIMARY KEY(session_id, track_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tracks_session_class ON vehicle_tracks(session_id, vehicle_class);
                CREATE TABLE IF NOT EXISTS tracked_objects (
                    session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id) ON DELETE CASCADE,
                    track_id TEXT NOT NULL,
                    object_class TEXT NOT NULL,
                    first_seen_s REAL NOT NULL,
                    last_seen_s REAL NOT NULL,
                    bbox_json TEXT NOT NULL,
                    trajectory_json TEXT NOT NULL,
                    confidence REAL,
                    speed_kmh REAL,
                    speed_quality TEXT NOT NULL,
                    helmet_class TEXT,
                    observations INTEGER NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0, 1)),
                    PRIMARY KEY(session_id, track_id)
                );
                CREATE INDEX IF NOT EXISTS idx_objects_session_class ON tracked_objects(session_id, object_class);
                CREATE TABLE IF NOT EXISTS violation_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id) ON DELETE CASCADE,
                    camera_id TEXT NOT NULL,
                    track_id TEXT,
                    event_type TEXT NOT NULL,
                    timestamp_s REAL,
                    confidence REAL,
                    speed_kmh REAL,
                    threshold_json TEXT NOT NULL DEFAULT '{}',
                    measurement_quality TEXT,
                    evidence_path TEXT,
                    review_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(review_status IN ('pending', 'verified', 'rejected')),
                    reviewer_decision TEXT,
                    reviewer TEXT,
                    reviewed_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_session_time ON violation_events(session_id, timestamp_s);
                CREATE INDEX IF NOT EXISTS idx_events_review ON violation_events(review_status, timestamp_s);
            """)
            # Upgrade existing databases: retain every previous vehicle row in the
            # generalized track history while leaving the compatibility table intact.
            conn.execute("""INSERT OR IGNORE INTO tracked_objects
                (session_id,track_id,object_class,first_seen_s,last_seen_s,bbox_json,
                 trajectory_json,confidence,speed_kmh,speed_quality,observations,active)
                SELECT session_id,track_id,vehicle_class,first_seen_s,last_seen_s,bbox_json,
                 trajectory_json,confidence,speed_kmh,speed_quality,observations,active
                FROM vehicle_tracks""")
            object_columns = {row[1] for row in conn.execute("PRAGMA table_info(tracked_objects)")}
            if "helmet_class" not in object_columns:
                conn.execute("ALTER TABLE tracked_objects ADD COLUMN helmet_class TEXT")
            conn.execute("PRAGMA user_version = 1")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_session(self, session_id: str, camera_id: str, source_mode: str,
                       input_name: str, model_name: str, calibration_status: str) -> None:
        with self._connect() as conn:
            conn.execute("""INSERT INTO analysis_sessions
                (session_id,camera_id,source_mode,input_name,model_name,calibration_status,status,started_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (session_id, camera_id, source_mode, input_name, model_name,
                 calibration_status, "queued", self._now()))
            now = self._now()
            conn.execute("""INSERT INTO cameras(camera_id,display_name,source_mode,created_at,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(camera_id) DO UPDATE SET
                display_name=excluded.display_name,source_mode=excluded.source_mode,updated_at=excluded.updated_at""",
                (camera_id, camera_id, source_mode, now, now))

    def update_session(self, session_id: str, status: str, frames_processed: int | None = None,
                       summary: dict | None = None, error_message: str | None = None,
                       calibration_status: str | None = None) -> None:
        completed = self._now() if status in {"completed", "failed", "cancelled"} else None
        with self._connect() as conn:
            conn.execute("""UPDATE analysis_sessions SET status=?,
                frames_processed=COALESCE(?,frames_processed),
                summary_json=COALESCE(?,summary_json),
                error_message=?, completed_at=COALESCE(?,completed_at),
                calibration_status=COALESCE(?,calibration_status)
                WHERE session_id=?""",
                (status, frames_processed,
                 json.dumps(summary, default=_json_default) if summary is not None else None,
                 error_message, completed, calibration_status, session_id))

    def save_tracks(self, session_id: str, tracks: dict) -> None:
        with self._connect() as conn:
            for track in tracks.get("tracks", []):
                object_class = str(track.get("object_class", track.get("vehicle_class", "unknown")))
                values = (session_id, track["track_id"], object_class, track["first_seen_s"],
                          track["last_seen_s"], json.dumps(track["bbox_xyxy"]),
                          json.dumps(track["trajectory"]), track.get("confidence"),
                          track.get("speed_kmh"), track["speed_quality"], track.get("helmet_class"),
                          track["observations"], int(track["active"]))
                conn.execute("""INSERT INTO tracked_objects
                    (session_id,track_id,object_class,first_seen_s,last_seen_s,bbox_json,
                     trajectory_json,confidence,speed_kmh,speed_quality,helmet_class,observations,active)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(session_id,track_id) DO UPDATE SET
                    object_class=excluded.object_class,first_seen_s=excluded.first_seen_s,
                    last_seen_s=excluded.last_seen_s,bbox_json=excluded.bbox_json,
                    trajectory_json=excluded.trajectory_json,confidence=excluded.confidence,
                    speed_kmh=excluded.speed_kmh,speed_quality=excluded.speed_quality,
                    helmet_class=excluded.helmet_class,
                    observations=excluded.observations,active=excluded.active""", values)
                if object_class == "pedestrian":
                    continue
                conn.execute("""INSERT INTO vehicle_tracks
                    (session_id,track_id,vehicle_class,first_seen_s,last_seen_s,bbox_json,
                     trajectory_json,confidence,speed_kmh,speed_quality,observations,active)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(session_id,track_id) DO UPDATE SET
                    vehicle_class=excluded.vehicle_class,first_seen_s=excluded.first_seen_s,
                    last_seen_s=excluded.last_seen_s,bbox_json=excluded.bbox_json,
                    trajectory_json=excluded.trajectory_json,confidence=excluded.confidence,
                    speed_kmh=excluded.speed_kmh,speed_quality=excluded.speed_quality,
                    observations=excluded.observations,active=excluded.active""",
                    (session_id, track["track_id"], object_class, track["first_seen_s"],
                     track["last_seen_s"], json.dumps(track["bbox_xyxy"]),
                     json.dumps(track["trajectory"]), track.get("confidence"), track.get("speed_kmh"),
                     track["speed_quality"], track["observations"], int(track["active"])))

    def insert_event(self, session_id: str, event: dict) -> bool:
        event_id = event.get("event_id")
        if not event_id:
            raise ValueError("event_id is required for event persistence")
        encounter = event.get("encounter") or {}
        with self._connect() as conn:
            cursor = conn.execute("""INSERT OR IGNORE INTO violation_events
                (event_id,session_id,camera_id,track_id,event_type,timestamp_s,confidence,speed_kmh,
                 threshold_json,measurement_quality,evidence_path,review_status,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, session_id, event.get("camera_id", "unspecified"), event.get("track_id"),
                 event.get("event_type", "review"), event.get("timestamp_s"), event.get("confidence"),
                 event.get("speed_kmh"), json.dumps({k: event[k] for k in
                     ("speed_limit_kmh", "tolerance_kmh", "confirmed_duration_s") if k in event}),
                 event.get("speed_quality") or encounter.get("risk"), event.get("evidence_path"),
                 event.get("review_status", "pending"), json.dumps(event, default=_json_default)))
            return cursor.rowcount == 1

    def review_event(self, event_id: str, decision: str, reviewer: str) -> None:
        if decision not in {"verified", "rejected"}:
            raise ValueError("review decision must be verified or rejected")
        reviewer = reviewer.strip()[:120]
        if not reviewer:
            raise ValueError("reviewer name is required")
        with self._connect() as conn:
            cursor = conn.execute("""UPDATE violation_events SET review_status=?,
                reviewer_decision=?,reviewer=?,reviewed_at=? WHERE event_id=?""",
                (decision, decision, reviewer, self._now(), event_id))
            if cursor.rowcount != 1:
                raise KeyError(event_id)

    def list_events(self, session_id: str, limit: int = 500) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("""SELECT payload_json,review_status,reviewer,reviewed_at
                FROM violation_events WHERE session_id=? ORDER BY timestamp_s DESC LIMIT ?""",
                (session_id, max(1, min(limit, 5000)))).fetchall()
        result = []
        for row in rows:
            event = json.loads(row["payload_json"])
            event.update(review_status=row["review_status"], reviewer=row["reviewer"], reviewed_at=row["reviewed_at"])
            result.append(event)
        return result

    def list_sessions(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("""SELECT session_id,camera_id,source_mode,input_name,model_name,
                calibration_status,status,started_at,completed_at,frames_processed,summary_json,error_message
                FROM analysis_sessions ORDER BY started_at DESC LIMIT ?""",
                (max(1, min(limit, 500)),)).fetchall()
        result = []
        for row in rows:
            record = dict(row)
            record["summary"] = json.loads(record.pop("summary_json"))
            result.append(record)
        return result

    def get_session(self, session_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("""SELECT session_id,camera_id,source_mode,input_name,model_name,
                calibration_status,status,started_at,completed_at,frames_processed,summary_json,error_message
                FROM analysis_sessions WHERE session_id=?""", (session_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["summary"] = json.loads(record.pop("summary_json"))
        return record

    def list_tracks(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("""SELECT track_id,object_class,first_seen_s,last_seen_s,bbox_json,
                trajectory_json,confidence,speed_kmh,speed_quality,helmet_class,observations,active
                FROM tracked_objects WHERE session_id=? ORDER BY CAST(track_id AS INTEGER),track_id""",
                (session_id,)).fetchall()
        tracks = []
        for row in rows:
            track = dict(row)
            track["bbox_xyxy"] = json.loads(track.pop("bbox_json"))
            track["trajectory"] = json.loads(track.pop("trajectory_json"))
            track["vehicle_class"] = track["object_class"]
            track["active"] = bool(track["active"])
            tracks.append(track)
        return tracks

    def analytics(self) -> dict:
        """Return aggregate counts and dated session activity from persisted rows."""
        with self._connect() as conn:
            session = conn.execute("""SELECT COUNT(*) AS sessions,
                COALESCE(SUM(status='completed'),0) AS completed,
                COALESCE(SUM(frames_processed),0) AS frames
                FROM analysis_sessions""").fetchone()
            tracks = conn.execute("""SELECT COUNT(*) AS tracks,
                COALESCE(SUM(speed_kmh IS NOT NULL),0) AS valid_speed
                FROM vehicle_tracks""").fetchone()
            pedestrians = conn.execute("SELECT COUNT(*) FROM tracked_objects WHERE object_class='pedestrian'").fetchone()[0]
            events = conn.execute("""SELECT COUNT(*) AS events,
                COALESCE(SUM(review_status='pending'),0) AS pending,
                COALESCE(SUM(review_status IN ('verified','rejected')),0) AS reviewed
                FROM violation_events""").fetchone()
            activity = conn.execute("""SELECT substr(started_at,1,10) AS day, COUNT(*) AS sessions
                FROM analysis_sessions GROUP BY day ORDER BY day DESC LIMIT 7""").fetchall()
        return {"sessions": int(session["sessions"]), "completed_sessions": int(session["completed"]),
                "frames_processed": int(session["frames"]), "vehicle_tracks": int(tracks["tracks"]),
                "tracks_with_valid_speed": int(tracks["valid_speed"]),
                "pedestrians": int(pedestrians),
                "events": int(events["events"]), "pending_events": int(events["pending"]),
                "reviewed_events": int(events["reviewed"]),
                "activity": [{"day": row["day"], "sessions": int(row["sessions"])} for row in reversed(activity)]}
