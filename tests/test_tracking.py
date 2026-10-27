import unittest

from safe_drive.tracking import TrackRegistry


class TrackRegistryTests(unittest.TestCase):
    def test_histories_are_independent_and_trajectory_is_retained(self):
        registry = TrackRegistry()
        registry.observe("1", 0.0, [0, 0, 10, 10], "car", 0.91, 12.0, "calibrated")
        registry.observe("2", 0.0, [20, 10, 40, 30], "motorcycle", 0.83)
        registry.observe("1", 1.0, [2, 0, 12, 10], "car", 0.88, 13.0, "calibrated")
        summary = registry.summary()
        self.assertEqual(summary["unique_track_ids"], 2)
        self.assertEqual(summary["tracks_with_valid_speed"], 1)
        self.assertEqual(summary["tracks"][0]["observations"], 2)
        self.assertEqual(summary["tracks"][1]["observations"], 1)
        self.assertEqual(summary["tracks"][1]["vehicle_class"], "motorcycle")

    def test_expiration_marks_track_completed_after_idle_window(self):
        registry = TrackRegistry(max_idle_seconds=1.0)
        registry.observe(7, 0.0, [1, 1, 5, 5], "bus", 0.7)
        self.assertEqual(registry.expire(0.9), [])
        self.assertEqual(registry.expire(1.1), ["7"])
        self.assertEqual(registry.summary()["completed_tracks"], 1)

    def test_unavailable_speed_is_never_fabricated(self):
        registry = TrackRegistry()
        registry.observe("x", 0.0, [0, 0, 10, 10], "truck", 0.6)
        self.assertIsNone(registry.summary()["tracks"][0]["speed_kmh"])
        self.assertEqual(registry.summary()["tracks_without_valid_speed"], 1)


if __name__ == "__main__":
    unittest.main()
