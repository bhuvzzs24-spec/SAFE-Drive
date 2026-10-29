"""One process is mandatory while jobs/limits use in-memory coordination."""
import os

production = os.environ.get("SAFE_DRIVE_ENV") == "production"
interface = os.environ.get("SAFE_DRIVE_BIND","0.0.0.0" if production else "127.0.0.1")
bind = f"{interface}:{int(os.environ.get('PORT','5170'))}"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 30
graceful_timeout = 15
preload_app = False
umask = 0o077
accesslog = None  # never log request bodies, query strings, auth headers or URLs
errorlog = "-"
loglevel = "warning"
capture_output = False
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 4096
forwarded_allow_ips = "127.0.0.1"  # proxy TLS handled explicitly by SAFE_DRIVE_TRUST_PROXY


def worker_exit(server,worker):
    import sys
    dashboard = sys.modules.get("app")
    if dashboard:
        for job in list(dashboard.JOBS.values()):
            if job.get("stop_event"):
                job["stop_event"].set()
