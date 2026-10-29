"""Synthetic codec + real DeepSORT interface smoke test. NO DETECTOR INFERENCE.

All rectangles/embeddings below are supplied fixture inputs, never AI results.
No model is loaded, no network is used, and no dashboard database is touched.
"""
import argparse
import faulthandler
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,required=True,help="new local scratch directory")
    parser.add_argument("--timeout",type=int,default=120,help="abort stalled native imports/test with traceback")
    args = parser.parse_args()
    faulthandler.dump_traceback_later(args.timeout,exit=True)
    print("Importing OpenCV / NumPy (bounded timeout)...",flush=True)
    import cv2
    import numpy as np
    from deep_sort_realtime.deepsort_tracker import DeepSort
    args.output_dir.mkdir(parents=True,exist_ok=False)
    source, annotated = args.output_dir/"synthetic-input.avi", args.output_dir/"synthetic-tracker.mp4"
    writer = cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*"MJPG"),10,(320,200))
    if not writer.isOpened():
        writer.release()
        raise RuntimeError("MJPG source encoder unavailable")
    try:
        for index in range(20):
            frame = np.full((200,320,3),28,np.uint8)
            x = 20+index*4
            cv2.rectangle(frame,(x,70),(x+35,110),(60,200,80),-1)
            cv2.putText(frame,"SYNTHETIC FIXTURE / NO DETECTOR",(5,22),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1)
            writer.write(frame)
    finally:
        writer.release()
    cap = cv2.VideoCapture(str(source))
    writer = cv2.VideoWriter(str(annotated),cv2.VideoWriter_fourcc(*"mp4v"),10,(320,200))
    if not cap.isOpened() or not writer.isOpened():
        cap.release()
        writer.release()
        raise RuntimeError("Synthetic decoder or mp4v output encoder unavailable")
    # Appearance embeddings and rectangles are known fixture inputs, not models.
    tracker = DeepSort(embedder=None,n_init=3,max_age=5)
    rows, observed_ids = [],set()
    try:
        for index in range(20):
            ok,frame = cap.read()
            if not ok:
                raise RuntimeError(f"Synthetic decode failed at frame {index}")
            x = 20+index*4
            tracks = tracker.update_tracks([([x,70,35,40],1.0,"fixture_rectangle")],
                                           embeds=[np.array([1.,0.,0.,0.])],frame=frame)
            ids = []
            for track in tracks:
                if not track.is_confirmed() or track.time_since_update:
                    continue
                box = track.to_ltrb(orig=True,orig_strict=True)
                if box is None:
                    raise RuntimeError("Matched track has no original detection box")
                tid = str(track.track_id)
                observed_ids.add(tid)
                ids.append(tid)
                x1,y1,x2,y2 = map(int,box)
                cv2.rectangle(frame,(x1,y1),(x2,y2),(255,180,0),2)
                cv2.putText(frame,f"FIXTURE ID {tid}",(x1,y1-8),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,180,0),1)
            rows.append({"frame":index,"timestamp_s":cap.get(cv2.CAP_PROP_POS_MSEC)/1000,"fixture_track_ids":ids})
            writer.write(frame)
            if index in (2,10,19):
                if not cv2.imwrite(str(args.output_dir/f"frame-{index:02d}.png"),frame):
                    raise RuntimeError("Cannot save smoke-test inspection frame")
    finally:
        cap.release()
        writer.release()
    if len(observed_ids) != 1 or any(len(row["fixture_track_ids"]) != 1 for row in rows[2:]):
        raise RuntimeError("Fixture identity consistency check failed")
    decoded = cv2.VideoCapture(str(annotated))
    count = 0
    try:
        while True:
            ok,frame = decoded.read()
            if not ok:
                break
            if frame.shape != (200,320,3):
                raise RuntimeError("Annotated frame size mismatch")
            count += 1
    finally:
        decoded.release()
    if count != 20:
        raise RuntimeError(f"Annotated roundtrip expected 20 frames, decoded {count}")
    report = {"kind":"synthetic_fixture_no_detector", "source_frames":20,"annotated_frames_decoded":count,
              "confirmed_fixture_ids":sorted(observed_ids),"rows":rows,
              "limitations":"Supplied boxes/embeddings; no detector, appearance model, real footage, accuracy or FPS evaluation."}
    (args.output_dir/"smoke.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "rows"},indent=2),flush=True)
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
