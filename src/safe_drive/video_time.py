"""Timestamp and annotated recording contracts, independent of OpenCV."""
import math


class FrameClock:
    def __init__(self, fps, mode="pts"):
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Video must declare a positive finite frame rate")
        if mode not in {"pts", "cfr", "arrival"}:
            raise ValueError("timestamp mode must be pts, cfr or arrival")
        self.fps, self.mode = fps, mode
        self.index, self.last, self.offset = 0, None, None

    def advance(self, position_ms=None, elapsed_s=None):
        if self.mode == "cfr":
            now = self.index / self.fps
        else:
            now = elapsed_s if self.mode == "arrival" else (position_ms / 1000 if position_ms is not None else None)
            if now is None or not math.isfinite(now) or now < 0:
                raise ValueError("Video timestamps must be finite and non-negative")
            if self.offset is None:
                self.offset = now
            now -= self.offset
        if self.last is not None and now <= self.last:
            raise ValueError("Video timestamps are repeated or reversed. Use timestamp mode cfr only for independently verified constant-frame-rate footage.")
        self.last, self.index = now, self.index + 1
        return now


class RecordingTimeline:
    """Resample source timestamps to the writer's CFR time grid using frame holds."""
    def __init__(self, writer, fps):
        self.writer, self.fps = writer, fps
        self.next_index, self.previous, self.last_timestamp = 0, None, None

    def write(self, frame, timestamp_s):
        if not math.isfinite(timestamp_s) or timestamp_s < 0 or (self.last_timestamp is not None and timestamp_s <= self.last_timestamp):
            raise ValueError("recording timestamps must be finite, non-negative and strictly increasing")
        target = math.floor(timestamp_s * self.fps + 0.5)
        # Avoid unbounded allocations on a corrupt timestamp jump.
        if target - self.next_index > self.fps * 10:
            raise ValueError("Video timestamp gap exceeds 10 seconds; split or repair the clip before analysis")
        while self.next_index < target:
            self.writer.write(self.previous if self.previous is not None else frame)
            self.next_index += 1
        if self.next_index == target:
            self.writer.write(frame)
            self.next_index += 1
        self.previous, self.last_timestamp = frame.copy(), timestamp_s
