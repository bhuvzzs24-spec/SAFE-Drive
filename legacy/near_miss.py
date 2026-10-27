# near_miss.py
import numpy as np

class NearMissDetector:
    def __init__(self, ttc_threshold=1.5, iou_threshold=0.05):
        self.ttc_threshold = ttc_threshold
        self.iou_threshold = iou_threshold

    def compute_iou(self, box1, box2):
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - intersection
        return intersection / union if union > 0 else 0

    def compute_ttc(self, box1, box2, speed1_kmh, speed2_kmh, pixel_to_m=0.05):
        c1x = (box1[0] + box1[2]) // 2
        c2x = (box2[0] + box2[2]) // 2
        gap_pixels = abs(c1x - c2x)
        gap_metres = gap_pixels * pixel_to_m
        rel_speed_ms = abs(speed1_kmh - speed2_kmh) / 3.6
        if rel_speed_ms < 0.5:
            return float('inf')
        ttc = gap_metres / rel_speed_ms
        return round(ttc, 2)

    def check_pair(self, box1, box2, speed1=0, speed2=0):
        iou = self.compute_iou(box1, box2)
        if iou >= self.iou_threshold:
            return True, f'OVERLAP (IoU={iou:.2f})', 0
        ttc = self.compute_ttc(box1, box2, speed1, speed2)
        if ttc < self.ttc_threshold:
            return True, f'TTC={ttc}s (DANGER)', ttc
        return False, 'SAFE', ttc

    def check_all_pairs(self, vehicles_with_speeds):
        near_misses = []
        n = len(vehicles_with_speeds)
        for i in range(n):
            for j in range(i + 1, n):
                v1 = vehicles_with_speeds[i]
                v2 = vehicles_with_speeds[j]
                flagged, reason, ttc = self.check_pair(
                    v1['box'], v2['box'],
                    v1.get('speed', 0), v2.get('speed', 0)
                )
                if flagged:
                    near_misses.append({
                        'id1': v1['id'],
                        'id2': v2['id'],
                        'reason': reason,
                        'ttc': ttc
                    })
        return near_misses