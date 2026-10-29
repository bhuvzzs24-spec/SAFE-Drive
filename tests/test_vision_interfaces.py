"""Contract tests with fake model/tracker objects. These are NOT AI inference."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from safe_drive.vision import (YoloDetector, clipped_box, detector_class_map,
                               local_detector_weights, observed_tracks)
from safe_drive.video_time import FrameClock, RecordingTimeline


def detection(box, cls=0, confidence=.9):
    tensor = Mock()
    tensor.cpu.return_value.numpy.return_value = np.array(box)
    return SimpleNamespace(xyxy=[tensor], cls=[cls], conf=[confidence])


def model_with(boxes, names=None, shape=(100, 200), task="detect"):
    model = Mock()
    model.task = task
    model.names = names if names is not None else {0: "car", 1: "person", 2: "tree"}
    model.return_value = [SimpleNamespace(boxes=boxes, orig_shape=shape)]
    return model


def track(tid="a", label="car", bbox=None, confirmed=True, age=0):
    t = Mock(track_id=tid, time_since_update=age)
    t.is_confirmed.return_value = confirmed
    t.to_ltrb.return_value = [10, 20, 40, 60] if bbox is None else bbox
    t.get_det_class.return_value = label
    t.get_det_conf.return_value = .8
    return t


class VisionInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((100, 200, 3), dtype=np.uint8)

    def test_local_weights_only_and_no_implicit_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("absent.pt", "https://example.org/a.pt", "model.onnx", "model.yaml", "model.engine"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    local_detector_weights(name)
            weights = Path(tmp)/"chosen.pt"
            weights.touch()
            with self.assertRaises(ValueError):
                local_detector_weights(weights)
            weights.write_bytes(b"not a real model: path validation only")
            self.assertEqual(local_detector_weights(weights), weights.resolve())

    def test_names_are_explicit_and_malformed_metadata_is_rejected(self):
        self.assertEqual(detector_class_map(["tree", "Motorbike", " person "]), {1:"motorcycle", 2:"pedestrian"})
        for names in ({-1:"car"}, {1.5:"car"}, {True:"car"}, {0:"car", "0":"bus"}, {0:None}):
            with self.subTest(names=names), self.assertRaises(ValueError):
                detector_class_map(names)
        with self.assertRaisesRegex(ValueError, "supported"):
            YoloDetector(model_with([], names={0:"helmet"}))
        for task in ("classify", "segment", "obb", "pose"):
            with self.subTest(task=task), self.assertRaisesRegex(ValueError, "task"):
                YoloDetector(model_with([], task=task))

    def test_original_xyxy_pixels_clipped_then_converted_to_ltwh(self):
        model = model_with([detection([-5, 10, 250, 80]), detection([4, 5, 9, 10], 1),
                            detection([1, 1, 9, 9], 2), detection([1, 1, 9, 9], 0, .1)])
        adapter = YoloDetector(model)
        self.assertEqual(adapter.detect(self.frame), [([0.,10.,200.,70.],.9,"car"), ([4.,5.,5.,5.],.9,"pedestrian")])
        self.assertIs(model.call_args.args[0], self.frame)
        self.assertEqual(model.call_args.kwargs, {"verbose":False, "conf":.35, "device":"cpu"})
        self.assertIsNone(clipped_box([201,0,300,50],200,100))

    def test_invalid_detector_outputs_fail_with_explanation(self):
        with self.assertRaisesRegex(ValueError,"uint8"):
            YoloDetector(model_with([])).detect(self.frame.astype(np.float32))
        for box in (detection([20,0,10,10]), detection([0,0,float("nan"),10]),
                    detection([0,0,10,10], .5), detection([0,0,10,10], 99), detection([0,0,10,10], 0, float("nan"))):
            with self.subTest(box=box), self.assertRaises(ValueError):
                YoloDetector(model_with([box])).detect(self.frame)
        with self.assertRaisesRegex(ValueError, "dimensions"):
            YoloDetector(model_with([],shape=(50,100))).detect(self.frame)
        with self.assertRaisesRegex(ValueError, "axis-aligned"):
            YoloDetector(model_with(None)).detect(self.frame)
        self.assertEqual(YoloDetector(model_with([])).detect(self.frame), [])

    def test_tracker_observations_exclude_predictions_and_tentatives(self):
        good = track()
        tracker = Mock()
        tracker.update_tracks.return_value = [good, track("b",confirmed=False), track("c",age=1)]
        items = observed_tracks(tracker, [], self.frame)
        tracker.update_tracks.assert_called_once_with([], frame=self.frame)
        self.assertEqual([(t.track_id,t.bbox_xyxy,t.object_class) for t in items], [("a",[10.,20.,40.,60.],"car")])
        good.to_ltrb.assert_called_once_with(orig=True, orig_strict=True)
        good.to_ltrb.return_value = None
        self.assertEqual(observed_tracks(tracker, [], self.frame), [])

    def test_tracker_rejects_duplicate_ids_and_unsupported_labels(self):
        tracker = Mock()
        for tracks in ([track(),track()], [track(label="vehicle")], [track(bbox=[9,0,1,10])]):
            tracker.update_tracks.return_value = tracks
            with self.assertRaises(ValueError):
                observed_tracks(tracker, [], self.frame)


class TimestampTests(unittest.TestCase):
    def test_pts_uses_variable_intervals_and_normalizes_first_frame(self):
        clock = FrameClock(30)
        np.testing.assert_allclose([clock.advance(t) for t in (1000,1040,1150)], [0,.04,.15], atol=1e-12)

    def test_pts_rejects_missing_duplicate_reversed_or_nonfinite_times(self):
        for bad in (None, float("nan"), -1, 0):
            clock = FrameClock(30)
            clock.advance(0)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clock.advance(bad)
        clock = FrameClock(30)
        clock.advance(100)
        with self.assertRaises(ValueError):
            clock.advance(99)
        for fps in (0,-1,float("nan"),float("inf")):
            with self.assertRaises(ValueError):
                FrameClock(fps)

    def test_explicit_cfr_and_live_arrival_timestamps(self):
        cfr = FrameClock(25,"cfr")
        self.assertEqual([cfr.advance() for _ in range(3)], [0,.04,.08])
        live = FrameClock(15,"arrival")
        self.assertEqual(live.advance(elapsed_s=2),0)
        self.assertEqual(live.advance(elapsed_s=2.5),.5)

    def test_recording_holds_frames_for_variable_timestamps(self):
        writer = Mock()
        recording = RecordingTimeline(writer,10)
        for n,t in enumerate((0,.1,.3)):
            recording.write(np.array([n]),t)
        self.assertEqual([int(c.args[0][0]) for c in writer.write.call_args_list], [0,1,1,2])
        self.assertEqual(recording.next_index,4)
        with self.assertRaises(ValueError):
            recording.write(np.array([3]),.2)
        with self.assertRaisesRegex(ValueError,"gap"):
            recording.write(np.array([3]),20)


if __name__ == "__main__":
    unittest.main()
