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

    def test_scaled_road_plane_bottom_centre_and_independent_distance(self):
        plane = RoadPlane([[0,0],[100,0],[100,100],[0,100]], [[0,0],[10,0],[10,20],[0,20]])
        np.testing.assert_allclose(plane.bottom_centres([[10,10,30,40]]), [[2,8]], atol=1e-9)
        # These endpoints were NOT fitting correspondences. Analytic 3-4-5 triangle.
        result = plane.validate_distances([{"image_points_px":[[10,10],[40,30]],"distance_m":5}])[0]
        self.assertAlmostEqual(result["estimated_distance_m"],5)
        self.assertLess(result["absolute_error_m"],1e-10)

    def test_perspective_fit_large_offsets_and_held_out_point(self):
        image = np.array([[0,0],[1000,0],[1000,800],[0,800],[250,300],[700,550]],float) + [1e6,2e6]
        h = np.array([[.01,.002,100],[-.001,.03,200],[1e-7,-1e-7,1]])
        def project(points):
            p = np.column_stack([points,np.ones(len(points))]) @ h.T
            return p[:,:2]/p[:,2:]
        plane = RoadPlane(image,project(image))
        holdout = [[1000500,2000400]]
        np.testing.assert_allclose(plane.transform(holdout),project(holdout),rtol=1e-10)

    def test_degenerate_correspondences_rejected_for_four_or_more_points(self):
        for count in (4,6):
            with self.subTest(count=count), self.assertRaises(ValueError):
                RoadPlane([[i,i] for i in range(count)], [[i,2*i] for i in range(count)])
        with self.assertRaises(ValueError):
            RoadPlane([[0,0],[0,0],[1,1],[0,1]], [[0,0],[1,0],[1,1],[0,1]])

    def test_nonfinite_points_bad_boxes_and_invalid_validation_distance(self):
        plane = RoadPlane([[0,0],[1,0],[1,1],[0,1]], [[0,0],[1,0],[1,1],[0,1]])
        for points in ([[float("nan"),1]], [1,2], [[1,2,3]]):
            with self.assertRaises(ValueError):
                plane.transform(points)
        with self.assertRaises(ValueError):
            plane.bottom_centres([[5,0,1,2]])
        with self.assertRaises(ValueError):
            plane.validate_distances([{"image_points_px":[[0,0],[1,1]], "distance_m":0}])
        self.assertEqual(plane.transform([]).shape,(0,2))

    def test_projective_horizon_is_rejected(self):
        # x'=x/(1-y/10), y'=y/(1-y/10); y=10 is the horizon.
        plane = RoadPlane([[0,0],[4,0],[4,5],[0,5]], [[0,0],[4,0],[8,10],[0,10]])
        with self.assertRaisesRegex(ValueError,"infinity"):
            plane.transform([[2,10]])


if __name__ == "__main__":
    unittest.main()
