"""Orchestration regression tests. Detector, tracker and video codec are STUBS.

Actual geometry, timestamps, speed rules, JSONL and SQLite are exercised. No
model accuracy, codec performance or real tracking quality is measured here.
"""
import importlib.machinery
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from safe_drive.cli import run_video
from safe_drive.rules import SpeedLimitRule
from safe_drive.storage import SQLiteStore


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root/"STUB-not-a-real-video.mp4"
        self.weights = self.root/"STUB-not-a-real-model.pt"
        self.input.write_bytes(b"stub input")
        self.weights.write_bytes(b"stub model")
        self.calibration = self.root/"calibration.json"
        self.calibration.write_text(json.dumps({"camera_id":"synthetic-contract-test",
            "image_size_px":[320,200], "image_points_px":[[0,0],[300,0],[300,200],[0,200]],
            "road_points_m":[[0,0],[30,0],[30,20],[0,20]]}))
        bundled = self.root/"embedder/weights/mobilenetv2_bottleneck_wts.pt"
        bundled.parent.mkdir(parents=True)
        bundled.write_bytes(b"stub embedder")
        self.frames = [np.zeros((200,320,3),np.uint8) for _ in range(20)]
        self.cursor = 0
        self.timestamps = [i*100 for i in range(20)]
        self.cap = Mock()
        self.cap.isOpened.return_value = True
        self.cap.read.side_effect = self.read
        self.cap.get.side_effect = self.get
        self.writer = Mock()
        self.writer.isOpened.return_value = True
        self.cv2 = ModuleType("cv2")
        for key,value in {"CAP_PROP_FPS":1,"CAP_PROP_FRAME_WIDTH":2,"CAP_PROP_FRAME_HEIGHT":3,
                          "CAP_PROP_POS_MSEC":4,"FONT_HERSHEY_SIMPLEX":0,"CAP_FFMPEG":42}.items():
            setattr(self.cv2,key,value)
        for key,value in {"VideoCapture":Mock(return_value=self.cap),"VideoWriter":Mock(return_value=self.writer),
                          "VideoWriter_fourcc":Mock(return_value=0),"rectangle":Mock(),"putText":Mock(),"polylines":Mock()}.items():
            setattr(self.cv2,key,value)
        self.model = Mock(task="detect",names={0:"car",1:"person"})
        self.model.side_effect = self.detect
        self.tracker = Mock()
        self.tracker.update_tracks.side_effect = self.update_tracks
        yolo = ModuleType("ultralytics")
        yolo.YOLO = Mock(return_value=self.model)
        package = ModuleType("deep_sort_realtime")
        package.__spec__ = importlib.machinery.ModuleSpec("deep_sort_realtime",None,origin=str(self.root/"__init__.py"),is_package=True)
        tracker_module = ModuleType("deep_sort_realtime.deepsort_tracker")
        tracker_module.DeepSort = Mock(return_value=self.tracker)
        self.modules = {"cv2":self.cv2,"ultralytics":yolo,"deep_sort_realtime":package,
                        "deep_sort_realtime.deepsort_tracker":tracker_module}
        self.store = SQLiteStore(self.root/"test.sqlite3")
        self.store.create_session("test","synthetic-contract-test","synthetic_fixture",self.input.name,self.weights.name,"configured")

    def read(self):
        if self.cursor >= len(self.frames):
            return False,None
        frame = self.frames[self.cursor].copy()
        self.cursor += 1
        return True,frame

    def get(self,key):
        return {1:10,2:320,3:200,4:self.timestamps[max(0,self.cursor-1)]}[key]

    def detect(self,frame,**kwargs):
        boxes = []
        for cls,x in ((0,20+5*(self.cursor-1)),(1,180-5*(self.cursor-1))):
            tensor = Mock()
            tensor.cpu.return_value.numpy.return_value = np.array([x,50,x+20,80])
            boxes.append(SimpleNamespace(cls=[cls],conf=[.9],xyxy=[tensor]))
        return [SimpleNamespace(orig_shape=(200,320),boxes=boxes)]

    def update_tracks(self,detections,frame):
        tracks = []
        for box,confidence,label in detections:
            x,y,w,h = box
            track = Mock(track_id={"car":"car-1","pedestrian":"ped-2"}[label],time_since_update=0)
            track.is_confirmed.return_value = True
            track.to_ltrb.return_value = [x,y,x+w,y+h]
            track.get_det_class.return_value = label
            track.get_det_conf.return_value = confidence
            tracks.append(track)
        return tracks

    def run_pipeline(self,calibration="default"):
        with patch.dict("sys.modules",self.modules), patch.dict("os.environ",{"SAFE_DRIVE_HELMET_MODEL":"","SAFE_DRIVE_TRACKER_WEIGHTS":"","SAFE_DRIVE_TIMESTAMP_MODE":"pts"}):
            # An empty override must not hide the bundled path during these tests.
            with patch.dict("os.environ",{},clear=False):
                import os
                os.environ.pop("SAFE_DRIVE_TRACKER_WEIGHTS",None)
                return run_video(self.input,self.calibration if calibration == "default" else calibration,
                    str(self.weights),self.root/"annotated.mp4",self.root/"events.jsonl",.35,
                    speed_rule=SpeedLimitRule(10,confirmation_s=.3),
                    event_callback=lambda event:self.store.insert_event("test",event))

    def test_calibrated_pipeline_ids_speeds_annotations_events_and_provenance(self):
        result = self.run_pipeline()
        self.assertEqual(result["frames_processed"],20)
        self.assertEqual(self.tracker.update_tracks.call_count,20)
        rows = [json.loads(line) for line in (self.root/"annotated.tracks.jsonl").read_text().splitlines()]
        self.assertEqual([[t["id"] for t in row["tracks"]] for row in rows],[["car-1","ped-2"]]*20)
        self.assertIsNone(rows[0]["tracks"][0]["velocity"])
        self.assertEqual(rows[-1]["tracks"][0]["speed"],18)
        self.assertTrue(all(row["tracks"][1]["speed"] is None for row in rows))
        self.assertEqual(self.writer.write.call_count,20)
        self.assertEqual(self.cv2.rectangle.call_count,40)
        labels = [call.args[1] for call in self.cv2.putText.call_args_list]
        self.assertTrue(any("car ID car-1" in label and "18.0 km/h" in label for label in labels))
        events = self.store.list_events("test")
        self.assertEqual({e["event_type"] for e in events},{"speed_limit_exceeded","approach_risk_screen"})
        self.assertTrue(all(isinstance(e["encounter"],dict) for e in events if "encounter" in e))
        manifest = json.loads((self.root/"annotated.run.json").read_text())
        self.assertEqual(len(manifest["provenance"]["model_sha256"]),64)
        self.assertEqual(manifest["timestamp_source"],"pts")
        self.cap.release.assert_called_once()
        self.writer.release.assert_called_once()

    def test_missing_calibration_keeps_tracking_but_no_metric_events(self):
        result = self.run_pipeline(None)
        self.assertEqual(result["calibration_status"],"unavailable")
        self.assertEqual(result["tracks"]["unique_track_ids"],2)
        self.assertTrue(all(t["speed_kmh"] is None for t in result["tracks"]["tracks"]))
        self.assertEqual(self.store.list_events("test"),[])

    def test_resolution_mismatch_disables_speed(self):
        data = json.loads(self.calibration.read_text())
        data["image_size_px"] = [640,400]
        self.calibration.write_text(json.dumps(data))
        result = self.run_pipeline()
        self.assertEqual(result["calibration_status"],"unavailable")
        self.assertIn("dimensions",result["calibration_message"])
        self.assertEqual(self.store.list_events("test"),[])

    def test_collinear_calibration_does_not_claim_metric_results(self):
        self.calibration.write_text(json.dumps({"image_points_px":[[0,0],[1,1],[2,2],[3,3]],
                                               "road_points_m":[[0,0],[1,0],[1,1],[0,1]]}))
        result = self.run_pipeline()
        self.assertEqual(result["calibration_status"],"unavailable")
        self.assertEqual(result["tracks"]["tracks_with_valid_speed"],0)

    def test_inference_error_releases_resources_and_has_no_completed_manifest(self):
        self.model.side_effect = RuntimeError("stub detector failure")
        with self.assertRaisesRegex(RuntimeError,"stub detector failure"):
            self.run_pipeline()
        self.cap.release.assert_called_once()
        self.writer.release.assert_called_once()
        self.assertFalse((self.root/"annotated.run.json").exists())

    def test_bad_timestamps_fail_and_release(self):
        self.timestamps[1] = 0
        with self.assertRaisesRegex(ValueError,"timestamps"):
            self.run_pipeline()
        self.cap.release.assert_called_once()
        self.writer.release.assert_called_once()

    def test_changed_frame_dimensions_fail_and_release(self):
        self.frames[1] = np.zeros((100,160,3),np.uint8)
        with self.assertRaisesRegex(ValueError,"dimensions changed"):
            self.run_pipeline()
        self.cap.release.assert_called_once()
        self.writer.release.assert_called_once()

    def test_zero_frame_source_and_unavailable_writer_are_explicit_failures(self):
        self.frames = []
        with self.assertRaisesRegex(SystemExit,"usable frame"):
            self.run_pipeline()
        self.cap.release.assert_called_once()
        self.writer.release.assert_called_once()

    def test_unavailable_writer_releases_capture(self):
        self.writer.isOpened.return_value = False
        with self.assertRaisesRegex(SystemExit,"Cannot create output"):
            self.run_pipeline()
        self.cap.release.assert_called_once()
        self.writer.release.assert_called_once()

    def test_existing_outputs_are_not_overwritten(self):
        output = self.root/"annotated.mp4"
        output.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError,"new output"):
            self.run_pipeline()
        self.assertEqual(output.read_bytes(),b"keep")
        self.cv2.VideoCapture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
