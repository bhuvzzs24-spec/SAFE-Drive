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


if __name__ == "__main__":
    unittest.main()
