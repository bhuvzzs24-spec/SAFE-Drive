"""Metric image-to-road-plane mapping for a fixed, calibrated camera."""
from __future__ import annotations

from dataclasses import dataclass
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

    def __post_init__(self) -> None:
        image = np.asarray(self.image_points, dtype=float)
        road = np.asarray(self.road_points_m, dtype=float)
        if image.ndim != 2 or road.ndim != 2 or image.shape != road.shape or image.shape[1] != 2:
            raise ValueError("image_points and road_points_m must be matching Nx2 arrays")
        if len(image) < 4 or not np.isfinite(image).all() or not np.isfinite(road).all():
            raise ValueError("at least four finite point correspondences are required")
        object.__setattr__(self, "image_points", image)
        object.__setattr__(self, "road_points_m", road)

    def transform(self, points: Sequence[Sequence[float]]) -> np.ndarray:
        """Map image points to metres using normalized DLT and least squares."""
        src = np.asarray(self.image_points, dtype=float)
        dst = np.asarray(self.road_points_m, dtype=float)
        # Solve Ah=0 via SVD; overdetermined point sets reduce calibration noise.
        rows = []
        for (x, y), (u, v) in zip(src, dst):
            rows.extend(([-x, -y, -1, 0, 0, 0, u*x, u*y, u],
                         [0, 0, 0, -x, -y, -1, v*x, v*y, v]))
        _, singular, vt = np.linalg.svd(np.asarray(rows, dtype=float))
        if singular[-1] < 1e-12 and len(src) == 4:
            raise ValueError("degenerate calibration points")
        h = vt[-1].reshape(3, 3)
        pts = np.asarray(points, dtype=float).reshape(-1, 2)
        p = np.column_stack((pts, np.ones(len(pts)))) @ h.T
        if np.any(np.abs(p[:, 2]) < 1e-10):
            raise ValueError("point maps to infinity under this calibration")
        return p[:, :2] / p[:, 2:3]

    def bottom_centres(self, boxes: Sequence[Sequence[float]]) -> np.ndarray:
        """Project each box's bottom-centre contact point onto the road plane."""
        points = [[(b[0] + b[2]) / 2, b[3]] for b in boxes]
        return self.transform(points)
