"""Supervisor with bounded wall time and suppressed native camera diagnostics."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


FAILURE_MESSAGES = {
    "detector_weights_unavailable":"Detector weights are missing or unsupported. Supply the configured local detection .pt checkpoint.",
    "helmet_weights_unavailable":"Helmet weights are missing or incompatible. Supply a three-class detection checkpoint or disable the optional helmet model.",
    "processing_failed":"Analysis failed. Check video decoding, model compatibility, calibration and worker limits.",
}

class JobFailure(RuntimeError):
    def __init__(self, code):
        self.code = code if code in FAILURE_MESSAGES else "processing_failed"
        super().__init__(FAILURE_MESSAGES[self.code])


def supervise_job(job_id,source,calibration,model,folder,database,stop_event,duration_s,source_label,speed_rule,timeout_s,progress):
    request_path = folder/"worker.request.json"
    config = {"id":job_id,"source":str(source),"calibration":str(calibration) if calibration else None,
              "model":model,"database":str(database),"duration_s":duration_s,"source_label":source_label,
              "speed_rule":asdict(speed_rule),"timeout_s":timeout_s}
    descriptor = os.open(request_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,"w") as target:
        json.dump(config,target)
    started, process, last_frames = time.monotonic(), None, -1
    try:
        inherited = {"PATH","LANG","LC_ALL","TZ","TMPDIR","SYSTEMROOT","WINDIR",
                     "DYLD_LIBRARY_PATH","LD_LIBRARY_PATH","SAFE_DRIVE_DEVICE",
                     "SAFE_DRIVE_TRACKER_WEIGHTS","SAFE_DRIVE_HELMET_MODEL","SAFE_DRIVE_TIMESTAMP_MODE",
                     "SAFE_DRIVE_HELMET_CONFIDENCE","SAFE_DRIVE_HELMET_ASSOCIATION_CONFIDENCE",
                     "SAFE_DRIVE_HELMET_MIN_HEAD_PIXELS","SAFE_DRIVE_HELMET_CONFIRM_S",
                     "SAFE_DRIVE_HELMET_MIN_OBSERVATIONS","SAFE_DRIVE_HELMET_MAX_GAP_S",
                     "SAFE_DRIVE_RISK_HORIZON_S","SAFE_DRIVE_RISK_TTC_S","SAFE_DRIVE_RISK_DISTANCE_M",
                     "SAFE_DRIVE_CAMERA_CONNECT_RETRIES"}
        env = {key:value for key,value in os.environ.items() if key in inherited}
        env.update(OMP_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1",YOLO_AUTOINSTALL="false",YOLO_OFFLINE="true",
                   YOLO_CONFIG_DIR=str(folder/"runtime-cache"))
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        # Do not pass web secrets/password hashes/camera config to native code.
        process = subprocess.Popen([sys.executable,"-m","safe_drive.worker",str(request_path)],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                   env=env,start_new_session=True)
        while process.poll() is None:
            if stop_event.is_set():
                (folder/"stop.request").touch()
            if time.monotonic()-started > timeout_s:
                raise TimeoutError("Analysis exceeded its configured processing deadline.")
            path = folder/"progress.json"
            if path.is_file():
                try:
                    value = json.loads(path.read_text())
                    if value["frames_processed"] > last_frames:
                        progress(value["frames_processed"],value["elapsed_s"],value["tracks"])
                        last_frames = value["frames_processed"]
                except (OSError,ValueError,KeyError):
                    pass
            time.sleep(.25)
        if process.returncode != 0 or not (folder/"result.json").is_file():
            code = "processing_failed"
            try:
                code = json.loads((folder/"failure.json").read_text()).get("code",code)
            except (OSError,ValueError,AttributeError):
                pass
            raise JobFailure(code)
        return json.loads((folder/"result.json").read_text())
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid,signal.SIGKILL)
            process.wait(timeout=5)
        request_path.unlink(missing_ok=True)
