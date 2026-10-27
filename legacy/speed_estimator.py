# speed_estimator.py
import numpy as np
from collections import defaultdict

class SpeedEstimator:
    def __init__(self, fps=30, pixel_to_meter=0.05):
        self.fps = fps
        self.pixel_to_meter = pixel_to_meter
        self.track_history = defaultdict(list)

    def update(self, track_id, cx, cy, frame_num):
        self.track_history[track_id].append((cx, cy, frame_num))
        if len(self.track_history[track_id]) > 15:
            self.track_history[track_id].pop(0)

    def get_speed(self, track_id):
        history = self.track_history[track_id]
        if len(history) < 5:
            return 0.0
        old_x, old_y, old_f = history[0]
        new_x, new_y, new_f = history[-1]
        pixel_dist = np.sqrt((new_x - old_x)**2 + (new_y - old_y)**2)
        real_dist = pixel_dist * self.pixel_to_meter
        time_sec = (new_f - old_f) / self.fps
        if time_sec == 0:
            return 0.0
        speed_kmh = (real_dist / time_sec) * 3.6
        return round(speed_kmh, 1)

    def clear_id(self, track_id):
        if track_id in self.track_history:
            del self.track_history[track_id]