import unittest

import numpy as np

from safe_drive.geometry import RoadPlane


class RoadPlaneTests(unittest.TestCase):
    def test_identity_calibration_maps_known_point(self):
        points = [[0, 0], [10, 0], [10, 10], [0, 10]]
        plane = RoadPlane(points, points)
        mapped = plane.transform([[5, 3]])[0]
        np.testing.assert_allclose(mapped, [5, 3], atol=1e-6)

    def test_invalid_correspondence_shape_is_rejected(self):
        with self.assertRaises(ValueError):
            RoadPlane([[0, 0], [1, 1]], [[0, 0], [1, 1]])


if __name__ == "__main__":
    unittest.main()
