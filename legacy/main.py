# main.py
import cv2
import numpy as np
from deep_sort_realtime.deepsort_tracker import DeepSort

from detector import Detector
from speed_estimator import SpeedEstimator
from near_miss import NearMissDetector
from plate_reader import PlateReader
from risk_engine import RiskEngine

SPEED_LIMIT = 60

def draw_annotations(frame, vehicles_data, near_misses):
    for v in vehicles_data:
        x1, y1, x2, y2 = v['box']
        color = (0, 0, 255) if v.get('violation') else (0, 255, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"ID:{v['id']}  {v['speed']}km/h"
        if not v.get('helmet', True):
            label += '  NO HELMET'
        cv2.putText(frame, label, (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    for nm in near_misses:
        cv2.putText(frame, f"NEAR MISS: {nm['reason']}",
                    (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    cv2.putText(frame, 'SAFE-Drive v1.0', (10, frame.shape[0] - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return frame

def process_video(input_path='test_video.mp4', output_path='output.mp4'):
    detector  = Detector('yolov8n.pt')
    tracker   = DeepSort(max_age=30)
    speeder   = SpeedEstimator(fps=30)
    nm_det    = NearMissDetector(ttc_threshold=1.5)
    plate_ocr = PlateReader()
    risk_eng  = RiskEngine()

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f'[ERROR] Cannot open: {input_path}')
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    W   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(output_path,
                          cv2.VideoWriter_fourcc(*'mp4v'), fps, (W, H))

    frame_num = 0
    print(f'[main] Processing: {input_path}')

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        vehicles, helmets, _ = detector.detect(frame)

        det_list = []
        for v in vehicles:
            x1, y1, x2, y2 = v['box']
            det_list.append(([x1, y1, x2 - x1, y2 - y1], v['conf'], v['class']))

        tracks = tracker.update_tracks(det_list, frame=frame)

        vehicles_data = []
        for track in tracks:
            if not track.is_confirmed():
                continue
            tid  = track.track_id
            ltrb = track.to_ltrb()
            cx   = int((ltrb[0] + ltrb[2]) // 2)
            cy   = int((ltrb[1] + ltrb[3]) // 2)

            speeder.update(tid, cx, cy, frame_num)
            speed = speeder.get_speed(tid)

            box        = [int(x) for x in ltrb]
            has_helmet = detector.check_helmet_for_rider(box, helmets) if helmets else True

            vehicles_data.append({
                'id'       : tid,
                'box'      : box,
                'speed'    : speed,
                'helmet'   : has_helmet,
                'violation': speed > SPEED_LIMIT or not has_helmet
            })

        near_misses = nm_det.check_all_pairs(vehicles_data)

        for v in vehicles_data:
            if v['violation'] or near_misses:
                plate_box = plate_ocr.find_plate_region(frame, v['box'])
                plate_num = plate_ocr.read_plate(frame, plate_box)
                result    = risk_eng.process(
                    plate_num, v['speed'], v['helmet'], bool(near_misses)
                )
                print(f"  Frame {frame_num:04d} | {plate_num} | "
                      f"Score:{result['score']} | {result['response']} | Rs.{result['fine']}")

        frame = draw_annotations(frame, vehicles_data, near_misses)
        out.write(frame)
        frame_num += 1

        if frame_num % 30 == 0:
            print(f'  Progress: {frame_num} frames done')

    cap.release()
    out.release()
    print(f'[main] Done! → {output_path}')

if __name__ == '__main__':
    process_video('test_video.mp4', 'output.mp4')