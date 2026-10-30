"""Optional video-file and RTSP runner; detector/tracker imports stay lazy."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import asdict
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
from pathlib import Path
import threading
import time

from .events import write_event
from .risk import score_event
from .rules import SpeedLimitRule, SpeedViolationConfirmer
from .speed import SpeedEstimator
from .tracking import TrackRegistry
from .video_time import FrameClock, RecordingTimeline
from .vision import (DETECTION_CLASSES, VEHICLE_CLASSES, YoloDetector,
                     detector_class_map, local_detector_weights, observed_tracks)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_video(video: Path | str, calibration: Path | None, model_path: str, out_video: Path,
              events_path: Path, confidence: float,
              stop_event: threading.Event | None = None, duration_s: int | None = None,
              source_label: str | None = None, progress_callback=None,
              speed_rule: SpeedLimitRule | None = None, event_callback=None,
              timestamp_mode: str | None = None, device: str | None = None,
              max_frames: int = 1800, max_pixels: int = 2073600,
              max_video_seconds: float = 60.0) -> dict:
    # Preflight before expensive imports, downloads or output allocation.
    weights = local_detector_weights(model_path)
    is_stream = str(video).lower().startswith(("rtsp://", "rtsps://"))
    if not is_stream and (not Path(video).is_file() or not Path(video).stat().st_size):
        raise ValueError("Input video is missing or empty")
    out_video, events_path = Path(out_video), Path(events_path)
    frame_log_path, manifest_path = out_video.with_suffix(".tracks.jsonl"), out_video.with_suffix(".run.json")
    targets = [out_video.resolve(), events_path.resolve(), frame_log_path.resolve(), manifest_path.resolve()]
    if len(set(targets)) != len(targets) or any(path.exists() for path in targets):
        raise ValueError("Use distinct, new output paths for each run; existing artifacts are never overwritten or appended.")
    if not math.isfinite(confidence) or not 0 < confidence <= 1:
        raise ValueError("confidence must be in (0, 1]")
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ["YOLO_OFFLINE"] = "true"
    if not is_stream:
        # File containers must not open nested HTTP/RTSP/network references.
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "protocol_whitelist;file"
    try:
        import cv2
        from ultralytics import YOLO
        from deep_sort_realtime.deepsort_tracker import DeepSort
    except ImportError as exc:
        raise SystemExit("Video mode needs optional dependencies: pip install -e '.[vision]'") from exc

    # Keep dashboard startup independent of the comparatively heavy vision
    # stack. Load numerical/geometry code only when a video job is submitted.
    import numpy as np
    from .encounters import analyse_pair
    from .geometry import RoadPlane

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
    device = device or os.environ.get("SAFE_DRIVE_DEVICE", "cpu")
    detector = YoloDetector(YOLO(str(weights), task="detect"), confidence, device)
    tracker_spec = importlib.util.find_spec("deep_sort_realtime")
    bundled_embedder = Path(tracker_spec.origin).parent / "embedder/weights/mobilenetv2_bottleneck_wts.pt"
    embedder_weights = Path(os.environ.get("SAFE_DRIVE_TRACKER_WEIGHTS", str(bundled_embedder))).expanduser().resolve()
    if not embedder_weights.is_file() or not embedder_weights.stat().st_size:
        raise ValueError("DeepSORT MobileNetV2 appearance weights are missing. Supply SAFE_DRIVE_TRACKER_WEIGHTS or the package's bundled checkpoint.")
    tracker = DeepSort(max_age=30, n_init=3, embedder="mobilenet", bgr=True,
                       half=False, embedder_gpu=False, embedder_wts=str(embedder_weights))
    from .helmet import HelmetReviewConfirmer, HELMET_CLASSES
    helmet_review = HelmetReviewConfirmer(float(os.environ.get("SAFE_DRIVE_HELMET_CONFIRM_S", "1")),
        int(os.environ.get("SAFE_DRIVE_HELMET_MIN_OBSERVATIONS", "5")),
        float(os.environ.get("SAFE_DRIVE_HELMET_MAX_GAP_S", ".5")))
    helmet_model = None
    helmet_weights = os.environ.get("SAFE_DRIVE_HELMET_MODEL", "").strip()
    if helmet_weights:
        from .helmet import HelmetInference
        helmet_model = HelmetInference.from_path(helmet_weights)
    risk_options = {"horizon_s":float(os.environ.get("SAFE_DRIVE_RISK_HORIZON_S","5")),
                    "ttc_threshold_s":float(os.environ.get("SAFE_DRIVE_RISK_TTC_S","1.5")),
                    "distance_threshold_m":float(os.environ.get("SAFE_DRIVE_RISK_DISTANCE_M","2"))}
    if not all(math.isfinite(v) and v>0 for v in risk_options.values()):
        raise ValueError("approach-risk thresholds must be finite and positive")
    retries = int(os.environ.get("SAFE_DRIVE_CAMERA_CONNECT_RETRIES","1")) if is_stream else 0
    if not 0 <= retries <= 2:
        raise ValueError("camera connection retries must be between zero and two")
    source_text = str(video)
    if is_stream and hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC") and hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
        params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000]
        cap = cv2.VideoCapture(source_text, cv2.CAP_FFMPEG, params)
    else:
        cap = cv2.VideoCapture(source_text if is_stream else str(video),cv2.CAP_FFMPEG)
    connection_attempts = 1
    while is_stream and not cap.isOpened() and connection_attempts <= retries:
        cap.release()
        cap = cv2.VideoCapture(source_text,cv2.CAP_FFMPEG,params) if hasattr(cv2,"CAP_PROP_OPEN_TIMEOUT_MSEC") and hasattr(cv2,"CAP_PROP_READ_TIMEOUT_MSEC") else cv2.VideoCapture(source_text,cv2.CAP_FFMPEG)
        connection_attempts += 1
    if not cap.isOpened():
        cap.release()
        raise SystemExit("Could not open the video source. Check the file or camera connection settings.")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if is_stream and (not np.isfinite(fps) or fps <= 0):
        fps = 15.0
    if not np.isfinite(fps) or fps <= 0:
        cap.release()
        raise SystemExit("Video has no valid frame rate; use a video with reliable timestamps")
    raw_width, raw_height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    if not all(math.isfinite(v) and v > 0 for v in (raw_width, raw_height)):
        cap.release()
        raise ValueError("Video source has invalid frame dimensions")
    width, height = int(raw_width), int(raw_height)
    if width*height > max_pixels or fps > 120:
        cap.release()
        raise ValueError("Video exceeds the configured resolution or frame-rate limit")
    mode = "arrival" if is_stream else timestamp_mode or os.environ.get("SAFE_DRIVE_TIMESTAMP_MODE", "pts")
    try:
        clock = FrameClock(fps, mode)
        if plane is not None and cal.get("image_size_px") is not None and cal["image_size_px"] != [width, height]:
            plane = None
            calibration_error = "Calibration image_size_px does not match the video dimensions. Speed is unavailable."
    except Exception:
        cap.release()
        raise
    try:
        out_video.parent.mkdir(parents=True, exist_ok=True)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        out_video_writer = cv2.VideoWriter(str(out_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    except Exception:
        cap.release()
        raise
    if not out_video_writer.isOpened():
        cap.release()
        out_video_writer.release()
        raise SystemExit(f"Cannot create output video: {out_video}")
    recording = RecordingTimeline(out_video_writer, fps)

    speed = SpeedEstimator()
    configured_rule = speed_rule or SpeedLimitRule(None)
    speed_rule = SpeedViolationConfirmer(configured_rule)
    locations = defaultdict(lambda: deque(maxlen=512))
    registry = TrackRegistry(max_idle_seconds=2.0, trail_length=40)
    cooldown = defaultdict(lambda: -10**9)
    frame_index = 0
    stream_started = time.monotonic()
    stream_ended = False
    event_source = source_label or ("live_camera" if is_stream else Path(video).name)
    frame_log = None
    try:
        events_path.touch(exist_ok=False)  # a zero-event run still has a JSONL artifact
        frame_log = frame_log_path.open("x", encoding="utf-8")
        while True:
            if stop_event and stop_event.is_set():
                break
            if is_stream and duration_s and time.monotonic() - stream_started >= duration_s:
                break
            ok, frame = cap.read()
            if not ok:
                stream_ended = is_stream and not (stop_event and stop_event.is_set())
                break
            if frame.shape != (height, width, 3):
                raise ValueError("Video frame dimensions changed during capture; recording/calibration would be invalid")
            now = clock.advance(cap.get(cv2.CAP_PROP_POS_MSEC), time.monotonic() - stream_started)
            if frame_index >= max_frames or (not is_stream and now > max_video_seconds):
                raise ValueError("Video exceeds the configured frame-count or duration limit; supply a shorter clip")
            for expired_id in registry.expire(now):
                speed.clear(expired_id)
                speed_rule.clear(expired_id)
                locations.pop(expired_id, None)
                helmet_review.clear(expired_id)
            detections = detector.detect(frame)
            tracks = observed_tracks(tracker, detections, frame)
            helmet_by_track = {}
            if helmet_model:
                people = [(t.track_id,t.bbox_xyxy) for t in tracks if t.object_class == "pedestrian"]
                motorcycles = [(t.track_id,t.bbox_xyxy) for t in tracks if t.object_class == "motorcycle"]
                if people and motorcycles:
                    helmet_by_track = helmet_model.associate_riders(people,motorcycles,helmet_model.detect(frame))
            for missing_id in set(helmet_review.history)-set(helmet_by_track):
                helmet_review.clear(missing_id)
            active = []
            for track in tracks:
                tid, box, vehicle_class = track.track_id, track.bbox_xyxy, track.object_class
                helmet_assessment = helmet_by_track.get(tid)
                helmet_class = helmet_assessment.class_name if helmet_assessment else None
                helmet_event = helmet_review.update(tid,helmet_assessment,now,frame_index)
                if helmet_event:
                    helmet_event.update(camera_id=cal.get("camera_id","unspecified"),source=event_source)
                    helmet_event["event_id"] = write_event(events_path,helmet_event)
                    if event_callback:
                        event_callback(helmet_event)
                track_confidence = track.confidence
                position = None
                estimate = None
                if plane is not None:
                    try:
                        x_m, y_m = plane.bottom_centres([box])[0]
                        position = (float(x_m), float(y_m))
                        locations[tid].append((now, *position))
                        while len(locations[tid]) > 2 and now - locations[tid][0][0] > 1.0:
                            locations[tid].popleft()
                        if vehicle_class != "pedestrian":
                            estimate = speed.update(tid, *position, now)
                            if estimate.quality == "implausible_speed_rejected":
                                locations[tid].clear()
                                locations[tid].append((now, *position))
                    except ValueError:
                        # A contact point at the horizon must not crash a job or
                        # retain old metric evidence for this object.
                        speed.clear(tid)
                        locations.pop(tid, None)
                velocity = None
                if position is not None and len(locations[tid]) >= 2:
                    a, b = locations[tid][0], locations[tid][-1]
                    dt = b[0] - a[0]
                    if dt >= speed.min_baseline_s:
                        velocity = ((b[1] - a[1]) / dt, (b[2] - a[2]) / dt)
                track_record = registry.observe(
                    tid, now, box, str(vehicle_class), track_confidence,
                    estimate.speed_kmh if estimate else None,
                    estimate.quality if estimate else "uncalibrated",
                    helmet_class=helmet_class,
                )
                speed_event = None
                if vehicle_class != "pedestrian":
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
                               "helmet_class": helmet_class,
                               "speed_violation": speed_event is not None})
                color = ((0, 0, 255) if speed_event else
                         (0, 200, 0) if estimate and estimate.speed_kmh is not None else (0, 180, 255))
                x1, y1, x2, y2 = map(int, box)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"{vehicle_class} ID {tid}"
                if track_confidence is not None:
                    label += f" {track_confidence:.2f}"
                speed_label = (f"{estimate.speed_kmh:.1f} km/h" if estimate and estimate.speed_kmh is not None
                               else "speed unavailable" if vehicle_class == "pedestrian" or plane is None
                               else "speed warming up" if estimate and estimate.quality == "warming_up" else "speed unavailable")
                label += " | " + speed_label
                if helmet_class:
                    label += " | " + helmet_class.replace("_", " ")
                if speed_event:
                    label += " | SPEED REVIEW"
                cv2.putText(frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2)
                points = [(int(px), int(py)) for px, py in track_record.trajectory]
                if len(points) >= 2:
                    cv2.polylines(frame, [np.asarray(points, dtype=np.int32)], False, color, 2)

            measurable = [item for item in active if item["position"] is not None and item["velocity"] is not None]
            for i, first in enumerate(measurable):
                for second in measurable[i + 1:]:
                    enc = analyse_pair(first["id"], second["id"], first["position"], first["velocity"],
                                       second["position"], second["velocity"], **risk_options)
                    if enc.risk not in ("high", "elevated"):
                        continue
                    pair = tuple(sorted((enc.track_a, enc.track_b)))
                    # Limit repeated alerts from one persistent encounter; events still include frame/time.
                    if now - cooldown[pair] < 2.0:
                        continue
                    cooldown[pair] = now
                    event_payload = {
                        "event_type": "approach_risk_screen", "source": event_source,
                        "camera_id": cal.get("camera_id", "unspecified"), "frame": frame_index,
                        "timestamp_s": round(now, 3), "encounter": asdict(enc),
                        "tracks": [first, second], "risk": score_event(None, False, None, True),
                        "review_required": True, "screening_thresholds": risk_options
                    }
                    eid = write_event(events_path, event_payload)
                    event_payload["event_id"] = eid
                    if event_callback:
                        event_callback(event_payload)
                    cv2.putText(frame, f"REVIEW: {enc.risk.upper()} APPROACH {eid[:8]}",
                                (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            frame_log.write(json.dumps({"frame": frame_index, "timestamp_s": now,
                                        "detections": len(detections), "tracks": active}, allow_nan=False) + "\n")
            recording.write(frame, now)
            frame_index += 1
            if progress_callback and frame_index % 30 == 0:
                progress_callback(frame_index, round(time.monotonic() - stream_started, 1), registry.summary())
    finally:
        cap.release()
        out_video_writer.release()
        if frame_log is not None:
            frame_log.close()
    if frame_index == 0:
        raise SystemExit("The source ended or stopped before delivering a usable frame.")
    registry.expire(now + registry.max_idle_seconds + 0.001)
    elapsed = time.monotonic() - stream_started
    result = {"frames_processed": frame_index, "source_ended": stream_ended,
            "stopped": bool(stop_event and stop_event.is_set()),
            "camera_connection_attempts": connection_attempts if is_stream else None,
            "camera_reconnect_policy": "Bounded initial retries; interrupted streams require a new session to preserve track/time provenance." if is_stream else None,
            "calibration_status": "calibrated" if plane is not None else "unavailable",
            "calibration_message": calibration_error, "tracks": registry.summary(),
            "timestamp_source": mode, "output_frames": recording.next_index,
            "timing_note": {"pts":"Decoded presentation timestamps, normalized to the first frame.",
                            "cfr":"User-selected constant-frame-rate assumption; verify against source metadata.",
                            "arrival":"Host arrival times include decoding/network delays; not validated camera capture times."}[mode],
            "processing_elapsed_s": elapsed, "processing_fps": frame_index / elapsed if elapsed > 0 else None,
            "frame_log": frame_log_path.name,
            "provenance": {"model_sha256": _sha256(weights), "model_name": weights.name,
                           "tracker_weights_sha256": _sha256(embedder_weights),
                           "input_sha256": None if is_stream else _sha256(video),
                           "calibration_sha256": _sha256(calibration) if calibration else None,
                           "device": device, "confidence": confidence,
                           "python": platform.python_version(), "platform": platform.platform(),
                           "code_sha256": {path.name: _sha256(path) for path in Path(__file__).parent.glob("*.py")},
                           "class_map": detector.class_map,
                           "source_fps": fps, "image_size_px": [width, height],
                           "speed_rule": asdict(configured_rule),
                           "screening_thresholds": risk_options,
                           "helmet_model_sha256": _sha256(Path(helmet_weights)) if helmet_weights else None,
                           "helmet_taxonomy": list(HELMET_CLASSES) if helmet_weights else None,
                           "helmet_review_rule": {"duration_s":helmet_review.duration_s,"min_observations":helmet_review.min_observations,"max_gap_s":helmet_review.max_gap_s},
                           "versions": {name: importlib.metadata.version(name) for name in
                                        ("numpy", "opencv-python", "ultralytics", "deep-sort-realtime", "torch", "torchvision")}}}
    manifest_path.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result


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
    video.add_argument("--timestamp-mode", choices=["pts", "cfr"], default=None,
                       help="decoded timestamps by default; cfr requires independently verified constant-rate video")
    video.add_argument("--device", default=None, help="Ultralytics device (default CPU or SAFE_DRIVE_DEVICE)")
    video.add_argument("--duration-sec", type=int, help="maximum live stream duration; ignored for video files")
    video.add_argument("--speed-limit-kmh", type=float, help="optional configured limit; disabled when omitted")
    video.add_argument("--speed-tolerance-kmh", type=float, default=0.0)
    video.add_argument("--speed-confirmation-sec", type=float, default=1.0)
    calibration_check = sub.add_parser("calibration-check", help="report fit residuals and supplied independent distance checks")
    calibration_check.add_argument("--calibration", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "video":
        result = run_video(args.input, args.calibration, args.model, args.output, args.events,
                  args.confidence, duration_s=args.duration_sec, timestamp_mode=args.timestamp_mode, device=args.device,
                  speed_rule=SpeedLimitRule(args.speed_limit_kmh, args.speed_tolerance_kmh,
                                            args.speed_confirmation_sec))
        print(json.dumps({"frames_processed": result["frames_processed"],
                          "manifest": str(args.output.with_suffix(".run.json")),
                          "frame_log": str(args.output.with_suffix(".tracks.jsonl"))}, indent=2))
    elif args.command == "calibration-check":
        import numpy as np
        from .geometry import RoadPlane
        config = json.loads(args.calibration.read_text(encoding="utf-8"))
        plane = RoadPlane(config["image_points_px"], config["road_points_m"])
        residual = plane.transform(plane.image_points) - plane.road_points_m
        checks = plane.validate_distances(config.get("validation_distances", []))
        print(json.dumps({"fit_rmse_m": float(np.sqrt(np.mean(np.sum(residual**2, axis=1)))),
                          "independent_distance_checks": checks,
                          "warning": "Fit residuals are not independent validation. Verify the survey, endpoint independence, camera pose and resolution."}, indent=2))


if __name__ == "__main__":
    main()
