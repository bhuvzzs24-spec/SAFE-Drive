"""Optional single-video runner; detector/tracker imports stay lazy."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import time

import numpy as np

from .encounters import analyse_pair
from .events import write_event
from .geometry import RoadPlane
from .risk import score_event
from .speed import SpeedEstimator

VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def run_video(video: Path, calibration: Path, model_path: str, out_video: Path,
              events_path: Path, speed_limit: float, confidence: float) -> None:
    try:
        import cv2
        from ultralytics import YOLO
        from deep_sort_realtime.deepsort_tracker import DeepSort
    except ImportError as exc:
        raise SystemExit("Video mode needs optional dependencies: pip install -e '.[vision]'") from exc

    cal = json.loads(calibration.read_text(encoding="utf-8"))
    plane = RoadPlane(cal["image_points_px"], cal["road_points_m"])
    detector = YOLO(model_path)
    tracker = DeepSort(max_age=30)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"Cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS)
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
    locations = defaultdict(lambda: deque(maxlen=8))
    cooldown = defaultdict(lambda: -10**9)
    frame_index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            now = frame_index / fps
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
                x_m, y_m = plane.bottom_centres([box])[0]
                estimate = speed.update(tid, float(x_m), float(y_m), now)
                locations[tid].append((now, float(x_m), float(y_m)))
                velocity = (0.0, 0.0)
                if len(locations[tid]) >= 2:
                    a, b = locations[tid][0], locations[tid][-1]
                    dt = b[0] - a[0]
                    if dt > 0:
                        velocity = ((b[1] - a[1]) / dt, (b[2] - a[2]) / dt)
                active.append({"id": tid, "box": box, "position": (x_m, y_m),
                               "velocity": velocity, "speed": estimate.speed_kmh,
                               "speed_quality": estimate.quality})
                color = (0, 200, 0) if estimate.speed_kmh is not None else (0, 180, 255)
                x1, y1, x2, y2 = map(int, box)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"ID {tid} | " + (f"{estimate.speed_kmh:.1f} km/h" if estimate.speed_kmh is not None else "calibrating")
                cv2.putText(frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2)

            for i, first in enumerate(active):
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
                    eid = write_event(events_path, {
                        "event_type": "approach_risk_screen", "video": video.name,
                        "camera_id": cal.get("camera_id", "unspecified"), "frame": frame_index,
                        "timestamp_s": round(now, 3), "encounter": enc,
                        "tracks": [first, second], "risk": score_event(None, False, None, True),
                        "review_required": True
                    })
                    cv2.putText(frame, f"REVIEW: {enc.risk.upper()} APPROACH {eid[:8]}",
                                (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            out_video_writer.write(frame)
            frame_index += 1
    finally:
        cap.release()
        out_video_writer.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrated SAFE-Drive video research runner")
    sub = parser.add_subparsers(dest="command", required=True)
    video = sub.add_parser("video", help="analyze one fixed-camera video")
    video.add_argument("--input", required=True, type=Path)
    video.add_argument("--calibration", required=True, type=Path)
    video.add_argument("--model", default="yolov8n.pt")
    video.add_argument("--output", type=Path, default=Path("outputs/annotated.mp4"))
    video.add_argument("--events", type=Path, default=Path("outputs/events.jsonl"))
    video.add_argument("--speed-limit-kmh", type=float, default=50.0,
                       help="reserved for configured advisory analyses; no automated enforcement")
    video.add_argument("--confidence", type=float, default=0.35)
    args = parser.parse_args()
    if args.command == "video":
        run_video(args.input, args.calibration, args.model, args.output, args.events,
                  args.speed_limit_kmh, args.confidence)


if __name__ == "__main__":
    main()
