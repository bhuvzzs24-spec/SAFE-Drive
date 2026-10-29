"""Analytic trajectory screening; no accident labels or validated incident model."""
import unittest
from safe_drive.encounters import analyse_pair


class EncounterTests(unittest.TestCase):
    def test_known_converging_trajectories_in_metres_and_seconds(self):
        event = analyse_pair("car","ped",[0,0],[1,0],[2,0],[-1,0])
        self.assertEqual(event.ttc_s,1)
        self.assertEqual(event.closest_distance_m,0)
        self.assertEqual(event.closing_speed_mps,2)
        self.assertEqual(event.risk,"high")

    def test_diverging_and_stationary_pairs_do_not_raise_approach_alerts(self):
        for velocities in (([-1,0],[1,0]),([0,0],[0,0]),([1,0],[1,0])):
            event = analyse_pair("a","b",[0,0],velocities[0],[1,0],velocities[1])
            self.assertEqual(event.risk,"low")
            self.assertIsNone(event.ttc_s)

    def test_invalid_or_missing_trajectories_and_thresholds(self):
        for vector in (None,[1],[1,2,3],[float("nan"),0]):
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                analyse_pair("a","b",vector,[0,0],[1,0],[0,0])
        with self.assertRaises(ValueError):
            analyse_pair("a","b",[0,0],[0,0],[1,0],[0,0],horizon_s=-1)
