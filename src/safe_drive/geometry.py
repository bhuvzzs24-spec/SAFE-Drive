"""Metric image-to-road-plane mapping for a fixed, calibrated camera."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class RoadPlane:
    """Homography mapping image pixels to road-plane metres.

    ``image_points`` and ``road_points_m`` are corresponding points on the road
    plane. At least four well-spread, non-collinear correspondences are needed.
    Speeds are meaningful only for the same fixed camera and calibration.
    """
    image_points: Sequence[Sequence[float]]
    road_points_m: Sequence[Sequence[float]]
    homography: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        image = np.asarray(self.image_points, dtype=float)
        road = np.asarray(self.road_points_m, dtype=float)
        if image.ndim != 2 or road.ndim != 2 or image.shape != road.shape or image.shape[1] != 2:
            raise ValueError("image_points and road_points_m must be matching Nx2 arrays")
        if len(image) < 4 or not np.isfinite(image).all() or not np.isfinite(road).all():
            raise ValueError("at least four finite point correspondences are required")
        image, road = image.copy(), road.copy()
        # Hartley normalization avoids unstable fits for large pixel coordinates
        # or large surveyed coordinate offsets. Fit once, not once per vehicle.
        def normalize(points):
            if len(np.unique(points, axis=0)) != len(points):
                raise ValueError("calibration correspondences must be distinct")
            centred = points - points.mean(axis=0)
            if np.linalg.matrix_rank(centred) < 2:
                raise ValueError("calibration points must not be collinear")
            scale = np.sqrt(2) / np.linalg.norm(centred, axis=1).mean()
            matrix = np.array([[scale, 0, -scale*points[:, 0].mean()],
                               [0, scale, -scale*points[:, 1].mean()], [0, 0, 1]])
            return centred * scale, matrix
        src, ti = normalize(image)
        dst, tr = normalize(road)
        rows = []
        for (x, y), (u, v) in zip(src, dst):
            rows.extend(([-x, -y, -1, 0, 0, 0, u*x, u*y, u],
                         [0, 0, 0, -x, -y, -1, v*x, v*y, v]))
        design = np.asarray(rows, dtype=float)
        if np.linalg.matrix_rank(design) < 8:
            raise ValueError("degenerate calibration correspondences")
        _, _, vt = np.linalg.svd(design, full_matrices=True)
        h = np.linalg.inv(tr) @ vt[-1].reshape(3, 3) @ ti
        h /= np.linalg.norm(h)
        if np.linalg.matrix_rank(vt[-1].reshape(3, 3)) < 3 or not np.isfinite(h).all():
            raise ValueError("singular calibration homography")
        for array in (image, road, h):
            array.setflags(write=False)
        object.__setattr__(self, "image_points", image)
        object.__setattr__(self, "road_points_m", road)
        object.__setattr__(self, "homography", h)
        self.transform(image)  # reject correspondences at the projective horizon

    def transform(self, points: Sequence[Sequence[float]]) -> np.ndarray:
        """Map finite Nx2 image coordinates to metres; reject the horizon."""
        pts = np.asarray(points, dtype=float)
        if pts.size == 0:
            return np.empty((0, 2))
        if pts.ndim != 2 or pts.shape[1] != 2 or not np.isfinite(pts).all():
            raise ValueError("image coordinates must be finite Nx2 arrays")
        p = np.column_stack((pts, np.ones(len(pts)))) @ self.homography.T
        if np.any(np.abs(p[:, 2]) <= 1e-12 * np.maximum(1, np.linalg.norm(p, axis=1))):
            raise ValueError("point maps to infinity under this calibration")
        return p[:, :2] / p[:, 2:3]

    def bottom_centres(self, boxes: Sequence[Sequence[float]]) -> np.ndarray:
        """Project each box's bottom-centre contact point onto the road plane."""
        boxes = np.asarray(boxes, dtype=float)
        if boxes.size == 0:
            return np.empty((0, 2))
        if boxes.ndim != 2 or boxes.shape[1] != 4 or not np.isfinite(boxes).all():
            raise ValueError("boxes must be finite Nx4 xyxy arrays")
        if np.any(boxes[:, 2:] <= boxes[:, :2]):
            raise ValueError("boxes must have positive width and height")
        points = [[(b[0] + b[2]) / 2, b[3]] for b in boxes]
        return self.transform(points)

    def validate_distances(self, measurements) -> list[dict]:
        """Evaluate separately surveyed distances; never treat fit residuals as validation.

        Each item: {image_points_px: [[x,y],[x,y]], distance_m: positive number}.
        Independence from the fitting points must be established by the caller.
        """
        reports = []
        for item in measurements:
            expected = float(item["distance_m"])
            points = np.asarray(item["image_points_px"], dtype=float)
            if points.shape != (2, 2) or not np.isfinite(expected) or expected <= 0:
                raise ValueError("validation requires two endpoints and a positive finite distance_m")
            mapped = self.transform(points)
            predicted = float(np.linalg.norm(mapped[1] - mapped[0]))
            reports.append({"distance_m": expected, "estimated_distance_m": predicted,
                            "absolute_error_m": abs(predicted-expected),
                            "relative_error": abs(predicted-expected)/expected})
        return reports
