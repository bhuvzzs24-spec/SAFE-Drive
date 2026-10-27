import unittest

from safe_drive.rules import SpeedLimitRule, SpeedViolationConfirmer


class SpeedRuleTests(unittest.TestCase):
    def test_boundary_includes_tolerance(self):
        confirmer = SpeedViolationConfirmer(SpeedLimitRule(50, tolerance_kmh=5, confirmation_s=0))
        self.assertIsNone(confirmer.update("1", 55, 0, "calibrated_estimate"))
        event = confirmer.update("1", 55.1, 0.1, "calibrated_estimate")
        self.assertEqual(event["event_type"], "speed_limit_exceeded")

    def test_event_requires_persistent_exceedance_and_is_deduplicated(self):
        confirmer = SpeedViolationConfirmer(SpeedLimitRule(50, confirmation_s=1.0, cooldown_s=10))
        self.assertIsNone(confirmer.update(3, 70, 0, "calibrated_estimate"))
        self.assertIsNone(confirmer.update(3, 70, 0.8, "calibrated_estimate"))
        event = confirmer.update(3, 72, 1.1, "calibrated_estimate")
        self.assertEqual(event["track_id"], "3")
        self.assertIsNone(confirmer.update(3, 75, 1.5, "calibrated_estimate"))

    def test_unavailable_speed_cannot_trigger_violation(self):
        confirmer = SpeedViolationConfirmer(SpeedLimitRule(50, confirmation_s=0))
        self.assertIsNone(confirmer.update("a", 120, 1, "uncalibrated"))
        self.assertIsNone(confirmer.update("a", None, 2, "warming_up"))

    def test_no_limit_means_rule_disabled(self):
        confirmer = SpeedViolationConfirmer(SpeedLimitRule(None))
        self.assertIsNone(confirmer.update("a", 120, 1, "calibrated_estimate"))

    def test_cooldown_survives_a_brief_drop_below_the_limit(self):
        confirmer = SpeedViolationConfirmer(SpeedLimitRule(50, confirmation_s=0, cooldown_s=20))
        self.assertIsNotNone(confirmer.update("a", 80, 0, "calibrated_estimate"))
        confirmer.update("a", 45, 1, "calibrated_estimate")
        self.assertIsNone(confirmer.update("a", 80, 2, "calibrated_estimate"))


if __name__ == "__main__":
    unittest.main()
