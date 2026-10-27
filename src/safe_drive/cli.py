"""Optional video-file and RTSP runner; detector/tracker imports stay lazy."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import threading
import time

import numpy as np

from .encounters import analyse_pair
from .events import write_event
from .geometry import RoadPlane
from .risk import score_event
from .rules import SpeedLimitRule, SpeedViolationConfirmer
from .speed import SpeedEstimator
from .tracking import TrackRegistry

VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def run_video(video: Path | str, calibration: Path | None, model_path: str, out_video: Path,
              events_path: Path, confidence: float,
              stop_event: threading.Event | None = None, duration_s: int | None = None,
              source_label: str | None = None, progress_callback=None,
              speed_rule: SpeedLimitRule | None = None, event_callback=None) -> dict:
    try:
        import cv2
        from ultralytics import YOLO
        from deep_sort_realtime.deepsort_tracker import DeepSort
    except ImportError as exc:
        raise SystemExit("Video mode needs optional dependencies: pip install -e '.[vision]'") from exc

    cal = {}
    plane = None
    calibration_error = "Calibration was not provided. Speed and metric TTC are unavailable."
    if calibration is not None:
        try:
            cal = json.loads(calibration.read_text(encoding="utf-8"))
            candidate = RoadPlane(cal["image_points_px"], cal["road_points_m"])
            candidate.transform(candidate.image_points)
            plane = candidate
            calibration_error = None
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            cal = {}
            calibration_error = "Calibration is invalid. Detection/tracking will continue; speed is unavailable."
    detector = YOLO(model_path)
    tracker = DeepSort(max_age=30)
    source_text = str(video)
    is_stream = source_text.lower().startswith(("rtsp://", "rtsps://"))
    if is_stream and hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC") and hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
        params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000]
        cap = cv2.VideoCapture(source_text, cv2.CAP_FFMPEG, params)
    else:
        cap = cv2.VideoCapture(source_text if is_stream else str(video))
    if not cap.isOpened():
        raise SystemExit("Could not open the video source. Check the file or camera connection settings.")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if is_stream and (not np.isfinite(fps) or fps <= 0):
        fps = 15.0
    if not np.isfinite(fps) or fps <= 0:
        cap.release()
        raise SystemExit("Video has no valid frame rate; use a video with reliable timestamps")
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out_video.parent.mkdir(parents=True, exist_ok=True)
    out_video_writer = cv2.VideoWriter(str(out_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not out_video_writer.isOpened():
        cap.release()
        raise SystemExit(f"Cannot create output video: {out_video}")

    speed = SpeedEstimator()
    speed_rule = SpeedViolationConfirmer(speed_rule or SpeedLimitRule(None))
    locations = defaultdict(lambda: deque(maxlen=8))
    registry = TrackRegistry(max_idle_seconds=2.0, trail_length=40)
    cooldown = defaultdict(lambda: -10**9)
    frame_index = 0
    stream_started = time.monotonic()
    stream_ended = False
    event_source = source_label or ("live_camera" if is_stream else Path(video).name)
    try:
        while True:
            if stop_event and stop_event.is_set():
                break
            if is_stream and duration_s and time.monotonic() - stream_started >= duration_s:
                break
            ok, frame = cap.read()
            if not ok:
                stream_ended = is_stream and not (stop_event and stop_event.is_set())
                break
            now = time.monotonic() - stream_started if is_stream else frame_index / fps
            detections = []
            result = detector(frame, verbose=False, conf=confidence)[0]
            for box in result.boxes:
                cls, conf = int(box.cls[0]), float(box.conf[0])
                if cls not in VEHICLE_CLASSES:
                    continue
                x1, y1, x2, y2 = map(float, box.xyxy[0].cpu().numpy())
                detections.append(([x1, y1, x2 - x1, y2 - y1], conf, VEHICLE_CLASSES[cls]))
            tracks = tracker.update_tracks(detections, frame=frame)
            active = []
            for track in tracks:
                if not track.is_confirmed() or track.time_since_update > 0:
                    continue
                tid = str(track.track_id)
                box = [float(v) for v in track.to_ltrb()]
                class_getter = getattr(track, "get_det_class", None)
                conf_getter = getattr(track, "get_det_conf", None)
                vehicle_class = (class_getter() if class_getter else None) or "vehicle"
                confidence_value = conf_getter() if conf_getter else None
                track_confidence = float(confidence_value) if confidence_value is not None else None
                position = None
                estimate = None
                if plane is not None:
                    x_m, y_m = plane.bottom_centres([box])[0]
                    position = (float(x_m), float(y_m))
                    estimate = speed.update(tid, *position, now)
                    locations[tid].append((now, *position))
                velocity = (0.0, 0.0)
                if position is not None and len(locations[tid]) >= 2:
                    a, b = locations[tid][0], locations[tid][-1]
                    dt = b[0] - a[0]
                    if dt > 0:
                        velocity = ((b[1] - a[1]) / dt, (b[2] - a[2]) / dt)
                track_record = registry.observe(
                    tid, now, box, str(vehicle_class), track_confidence,
                    estimate.speed_kmh if estimate else None,
                    estimate.quality if estimate else "uncalibrated",
                )
                speed_event = speed_rule.update(
                    tid, estimate.speed_kmh if estimate else None, now,
                    estimate.quality if estimate else "uncalibrated", track_confidence,
                )
                if speed_event:
                    speed_event.update({"camera_id": cal.get("camera_id", "unspecified"),
                                        "source": event_source, "frame": frame_index})
                    event_id = write_event(events_path, speed_event)
                    speed_event["event_id"] = event_id
                    if event_callback:
                        event_callback(speed_event)
                active.append({"id": tid, "box": box, "position": position,
                               "velocity": velocity, "speed": estimate.speed_kmh if estimate else None,
                               "speed_quality": estimate.quality if estimate else "uncalibrated",
                               "class": str(vehicle_class), "confidence": track_confidence,
                               "speed_violation": speed_event is not None})
                color = ((0, 0, 255) if speed_event else
                         (0, 200, 0) if estimate and estimate.speed_kmh is not None else (0, 180, 255))
                x1, y1, x2, y2 = map(int, box)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"{vehicle_class} ID {tid}"
                if track_confidence is not None:
                    label += f" {track_confidence:.2f}"
                label += " | " + (f"{estimate.speed_kmh:.1f} km/h" if estimate and estimate.speed_kmh is not None else "Uncalibrated — speed unavailable" if plane is None else "calibrating")
                if speed_event:
                    label += " | SPEED REVIEW"
                cv2.putText(frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2)
                points = [(int(px), int(py)) for px, py in track_record.trajectory]
                if len(points) >= 2:
                    cv2.polylines(frame, [np.asarray(points, dtype=np.int32)], False, color, 2)

            for i, first in enumerate(active if plane is not None else []):
                for second in active[i + 1:]:
                    enc = analyse_pair(first["id"], second["id"], first["position"], first["velocity"],
                                       second["position"], second["velocity"])
                    if enc.risk not in ("high", "elevated"):
                        continue
                    pair = tuple(sorted((enc.track_a, enc.track_b)))
                    # Limit repeated alerts from one persistent encounter; events still include frame/time.
                    if frame_index - cooldown[pair] < int(fps * 2):
                        continue
                    cooldown[pair] = frame_index
                    event_payload = {
                        "event_type": "approach_risk_screen", "source": event_source,
                        "camera_id": cal.get("camera_id", "unspecified"), "frame": frame_index,
                        "timestamp_s": round(now, 3), "encounter": enc,
                        "tracks": [first, second], "risk": score_event(None, False, None, True),
                        "review_required": True
                    }
                    eid = write_event(events_path, event_payload)
                    event_payload["event_id"] = eid
                    if event_callback:
                        event_callback(event_payload)
                    cv2.putText(frame, f"REVIEW: {enc.risk.upper()} APPROACH {eid[:8]}",
                                (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            out_video_writer.write(frame)
            frame_index += 1
            expired = registry.expire(now)
            for expired_id in expired:
                speed.clear(expired_id)
                speed_rule.clear(expired_id)
                locations.pop(expired_id, None)
            if progress_callback and frame_index % 30 == 0:
                progress_callback(frame_index, round(time.monotonic() - stream_started, 1), registry.summary())
    finally:
        cap.release()
        out_video_writer.release()
    if frame_index == 0:
        raise SystemExit("The source ended or stopped before delivering a usable frame.")
    registry.expire(now + registry.max_idle_seconds + 0.001)
    return {"frames_processed": frame_index, "source_ended": stream_ended,
            "stopped": bool(stop_event and stop_event.is_set()),
            "calibration_status": "calibrated" if plane is not None else "unavailable",
            "calibration_message": calibration_error, "tracks": registry.summary()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrated SAFE-Drive video research runner")
    sub = parser.add_subparsers(dest="command", required=True)
    video = sub.add_parser("video", help="analyze a fixed-camera video file or RTSP stream")
    video.add_argument("--input", required=True, help="video file path or RTSP/RTSPS URL")
    video.add_argument("--calibration", type=Path, help="optional measured camera homography JSON")
    video.add_argument("--model", default="yolov8n.pt")
    video.add_argument("--output", type=Path, default=Path("outputs/annotated.mp4"))
    video.add_argument("--events", type=Path, default=Path("outputs/events.jsonl"))
    video.add_argument("--confidence", type=float, default=0.35)
    video.add_argument("--duration-sec", type=int, help="maximum live stream duration; ignored for video files")
    video.add_argument("--speed-limit-kmh", type=float, help="optional configured limit; disabled when omitted")
    video.add_argument("--speed-tolerance-kmh", type=float, default=0.0)
    video.add_argument("--speed-confirmation-sec", type=float, default=1.0)
    args = parser.parse_args()
    if args.command == "video":
        run_video(args.input, args.calibration, args.model, args.output, args.events,
                  args.confidence, duration_s=args.duration_sec,
                  speed_rule=SpeedLimitRule(args.speed_limit_kmh, args.speed_tolerance_kmh,
                                            args.speed_confirmation_sec))


if __name__ == "__main__":
    main()
