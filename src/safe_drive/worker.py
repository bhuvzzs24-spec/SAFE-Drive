"""Private bounded job subprocess. Never print sources, credentials or exceptions."""
import json
import os
from pathlib import Path
import sys
import threading


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value),encoding="utf-8")
    temp.replace(path)


class StopFile:
    def __init__(self,path):
        self.path = path
    def is_set(self):
        return self.path.exists()


def main():
    os.umask(0o077)
    request_path = Path(sys.argv[1])
    config = json.loads(request_path.read_text())
    request_path.unlink()  # camera source never retained after worker starts
    folder = request_path.parent
    # Hard wall limit includes native imports; the parent also enforces it.
    watchdog = threading.Timer(config["timeout_s"]+5,lambda:os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(config["timeout_s"],config["timeout_s"]+1))
        resource.setrlimit(resource.RLIMIT_FSIZE,(512*1024*1024,512*1024*1024))
        resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
        from .vision import local_detector_weights
        try:
            local_detector_weights(config["model"])
        except (ValueError,OSError):
            atomic_json(folder/"failure.json",{"code":"detector_weights_unavailable"})
            return 1
        if os.environ.get("SAFE_DRIVE_HELMET_MODEL"):
            try:
                local_detector_weights(os.environ["SAFE_DRIVE_HELMET_MODEL"])
            except (ValueError,OSError):
                atomic_json(folder/"failure.json",{"code":"helmet_weights_unavailable"})
                return 1
        from .cli import run_video
        from .rules import SpeedLimitRule
        from .storage import SQLiteStore
        store = SQLiteStore(config["database"])
        def progress(frames,elapsed,tracks):
            store.save_tracks(config["id"],tracks)
            store.update_session(config["id"],"running",frames)
            atomic_json(folder/"progress.json",{"frames_processed":frames,"elapsed_s":elapsed,"tracks":tracks})
        result = run_video(config["source"],Path(config["calibration"]) if config["calibration"] else None,
            config["model"],folder/"annotated.mp4",folder/"events.jsonl",.35,
            StopFile(folder/"stop.request"),config["duration_s"],config["source_label"],progress,
            SpeedLimitRule(**config["speed_rule"]),lambda event:store.insert_event(config["id"],event))
        atomic_json(folder/"result.json",result)
    except BaseException:
        atomic_json(folder/"failure.json",{"code":"processing_failed"})
        raise SystemExit(1) from None
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main() or 0)
