import unittest

from safe_drive.speed import SpeedEstimator


class SpeedEstimatorTests(unittest.TestCase):
    def test_known_ground_plane_distance_and_timestamp(self):
        estimator = SpeedEstimator(window_s=1, min_baseline_s=0.25, max_baseline_s=2)
        self.assertIsNone(estimator.update("a", 0, 0, 0).speed_kmh)
        result = estimator.update("a", 10, 0, 1)
        self.assertAlmostEqual(result.speed_kmh, 36.0)
        self.assertEqual(result.quality, "calibrated_estimate")

    def test_implausible_measurement_is_rejected(self):
        estimator = SpeedEstimator(window_s=1, min_baseline_s=0.25, max_baseline_s=2, max_speed_kmh=200)
        estimator.update("a", 0, 0, 0)
        result = estimator.update("a", 100, 0, 1)
        self.assertIsNone(result.speed_kmh)
        self.assertEqual(result.quality, "implausible_speed_rejected")

    def test_timestamp_reset_and_long_gap_clear_smoothing(self):
        for next_time in (0,1,10):
            e = SpeedEstimator()
            e.update("a",0,0,0)
            self.assertEqual(e.update("a",10,0,1).speed_kmh,36)
            self.assertIsNone(e.update("a",0,0,next_time).speed_kmh)
            self.assertEqual(e.update("a",20,0,next_time+1).speed_kmh,72)

    def test_irregular_intervals_units_insufficient_history_and_missing_track(self):
        e = SpeedEstimator()
        self.assertIsNone(e.update("a",0,0,0).speed_kmh)
        self.assertIsNone(e.update("a",1,0,.1).speed_kmh)
        self.assertEqual(e.update("a",5,0,.5).speed_kmh,36)
        self.assertIsNone(e.update("new",5,0,.5).speed_kmh)
        e.clear("a")
        self.assertIsNone(e.update("a",15,0,1.5).speed_kmh)
        for value in (float("nan"),float("inf"),-1):
            with self.assertRaises(ValueError):
                e.update("a",0,0,value)

    def test_teleport_rejection_starts_new_segment(self):
        e = SpeedEstimator()
        e.update("a",0,0,0)
        self.assertIsNone(e.update("a",100,0,1).speed_kmh)
        self.assertEqual(e.update("a",110,0,2).speed_kmh,36)


if __name__ == "__main__":
    unittest.main()
