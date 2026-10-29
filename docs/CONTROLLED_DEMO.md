# Controlled public demo: deployment preparation

No service has been deployed or exposed as part of this change. `render.yaml` is an inert template. Creating its service and persistent disk would incur hosting charges; do that only after explicit approval and a cost review. Automatic deployment is disabled in the template.

## Security boundary

Public mode is `SAFE_DRIVE_ENV=production`. It requires a random `SAFE_DRIVE_SECRET` of at least 32 characters and exact `SAFE_DRIVE_ALLOWED_HOSTS` (comma-separated names, without schemes, ports or wildcards). It uses Gunicorn, never the Flask development server. HTTPS terminates at the hosting proxy. Only set `SAFE_DRIVE_TRUST_PROXY=1` when there is exactly one trusted TLS proxy that replaces incoming forwarded headers and the origin cannot be reached directly; only forwarded scheme is trusted, not host/client-IP headers.

Anonymous visitors can view the interface, `/healthz`, and an explicitly configured licensed **sample video**. Their session history and analytics describe the empty public scope; no private sessions, counts, tracks, reviews or evidence are returned. Sample playback is labeled **no inference**. No demo footage, detection results or model weights are invented or bundled. Supply `SAFE_DRIVE_SAMPLE_VIDEO` and `SAFE_DRIVE_SAMPLE_LICENSE` to enable playback; the video is served from that fixed operator-controlled path, never a request path. Do not point this setting at private footage.

Sensitive routes require an authenticated account. All authorized accounts share one research workspace; this is **not tenant/user-isolated storage**. Roles:

| Role | Read private sessions/evidence | Upload/stop jobs, if enabled | Review events | Public-host camera access |
| --- | --- | --- | --- | --- |
| Public | No | No | No | No |
| Analyst | Yes | Yes | No | No |
| Reviewer | Yes | No | Yes | No |
| Admin | Yes | Yes | Yes | No |

`SAFE_DRIVE_USERS_JSON` is a secret environment JSON mapping usernames to `password_hash` and `role`. Generate a Werkzeug hash offline using:

```bash
.venv/bin/python scripts/demo_admin.py password-hash
```

The command prompts without echo; it requires matching passwords of at least 16 characters. Put the resulting hash in the host's secret/environment UI, in this JSON structure:

```json
{"your_operator_name":{"password_hash":"PASTE_GENERATED_WERKZEUG_HASH","role":"admin"}}
```

There is no default account/password, registration or password-reset endpoint. Passwords are checked against hashes. Login rotates the signed session and CSRF token. Production cookies are Secure, HttpOnly, SameSite=Lax, with a fixed 30-minute lifetime; no role/password/credential is stored in the cookie. The username and password-hash fingerprint are checked against current configuration on every request. Removing an account or changing its password hash invalidates its sessions after the service reloads the new environment. Role changes likewise take effect when configuration reloads. Logout clears the browser cookie; a previously stolen cookie remains usable until expiry or server-side account/secret rotation. No MFA/SSO or per-session revocation store is implemented.

Every mutation (including login/logout) requires CSRF protection, and production POSTs require HTTPS. Login has a bounded one-process global attempt budget. A trusted edge/WAF must additionally rate-limit requests, body sizes and connections; the app's login budget is not a distributed abuse-control service. HSTS, nosniff, frame denial, CSP, no-store, no-referrer and a restrictive browser permissions policy are set. `/healthz` returns only `{"status":"ok"}` and is a liveness check, not a model/database-readiness claim.

Local mode remains loopback-only and trusts local requests as an operator to preserve the research workflow. **Never bind local mode to a public or shared network**, proxy it publicly, or use its bypass as hosted authentication. Gunicorn binds loopback unless production mode is explicitly selected; a local production smoke test should set `SAFE_DRIVE_BIND=127.0.0.1`.

## Uploads and processing

Hosted uploads are **disabled by default** (`SAFE_DRIVE_ALLOW_UPLOADS=0`). Enabling them is a separate operator decision after validating the native vision stack, supplying trusted compatible models, and sizing the host. Anonymous uploads remain forbidden. Production uses only `SAFE_DRIVE_MODEL`; a form cannot select another server path/model. The public template installs base + deployment dependencies only; real inference additionally needs the vision extra, compatible weights and native runtime verification described in `VISION_INTEGRATION.md`.

Configured controls:

- Default hosted request limit: 30 MiB (`SAFE_DRIVE_MAX_UPLOAD=31457280`), with an absolute app ceiling of 300 MiB. Forms are bounded to 64 KiB memory and eight parts. Calibration JSON is limited to 64 KiB and 256 correspondences.
- Accepted video-container extensions plus matching basic signatures: MP4/MOV `ftyp`, AVI RIFF/AVI, MKV/WEBM EBML. Signatures are preliminary validation, **not proof of a valid or safe video**; the decoder must still succeed.
- Server-generated UUID directories and fixed input names, path confinement on evidence reads, rejection of symlink escapes, private job-directory permissions, and no request-selected file paths.
- One running job and at most one queued job per process; excess submissions return 429. Disk checks reject further work when the configured free-space/data limits are reached (507).
- Each job runs in a private subprocess with a 120-second wall deadline by default, a parent kill deadline, a child watchdog/CPU limit, a 512 MiB per-file write ceiling and a file-descriptor ceiling. Decode limits default to 1080p, 120 FPS, 1,800 frames and 60 seconds for files. Long/oversized sources fail rather than silently claiming complete analysis. Adjust deployment capacity before changing these limits.
- File inputs force the FFmpeg backend with a `file` protocol whitelist; nested HTTP/RTSP references are not permitted. This requires an OpenCV build with FFmpeg. Native parsers still process untrusted binary content: subprocesses and limits are **not an OS sandbox**. For anything beyond invited, controlled operators, use a dedicated restricted container/worker, read-only filesystem, patched codecs and enforced network egress policy before accepting uploads.

Raw native stdout/stderr is discarded for workers, which prevents FFmpeg camera diagnostics from publishing credentials. Web/application logs record only generated job IDs and error categories, never request bodies, exception text, stream URLs or authentication headers. Child environment inheritance is restricted; web session secrets, user hashes and unrelated host credentials are not passed to vision workers. Gunicorn access logging is disabled; review the host/proxy's own logging and retention settings separately.

The queue is intentionally single-instance/in-memory. Use **one Gunicorn worker and one host instance** as configured. Do not use preloading, multiple workers, autoscaling, or multiple services against the same SQLite/files directory. Jobs are not durable/retryable. Startup marks queued/running/stopping sessions as failed instead of reconnecting to a camera or pretending analysis completed. Saved completed sessions, tracks, events and reviews remain readable after restart. A failed/timed-out job can retain partial artifacts for operator review; they are not served as completed recordings. There is no automatic inference retry.

## Cameras and SSRF

Live cameras are **unconditionally disabled in production HTTP mode**, including for admins and even if `SAFE_DRIVE_ENABLE_CAMERAS=1` is set accidentally. Public and privileged camera operations are separate deployments/network boundaries, not a toggle exposed to visitors.

For a separately secured **local/private** operator instance only, explicit `SAFE_DRIVE_ENABLE_CAMERAS=1` permits the single server-registered RTSP source. Clients cannot submit or replace its URL. The source must use an IP literal in `SAFE_DRIVE_CAMERA_ALLOWED_IPS`, on RTSP 554 or RTSPS 322 (or default), and cannot target loopback, link-local/cloud metadata, unspecified, multicast or reserved addresses. DNS names are rejected, removing DNS rebinding at this boundary. Keep its actual URL/credentials in the host environment or ignored private config, never Git.

RTSP servers/protocol handlers can redirect or otherwise fetch secondary destinations. Therefore the private camera instance **also requires a firewall/container egress allowlist** permitting only the registered camera IP/port; the application allowlist alone does not validate all native protocol behavior. No claim is made that a real camera, TLS camera certificate or redirection path was tested. Never enable camera credentials on the public demo instance.

## SQLite, files, backups and retention

Set both `SAFE_DRIVE_DATA` and `SAFE_DRIVE_DATABASE` under the same persistent volume. The supplied template uses `/var/data/safe-drive` and `/var/data/safe-drive/safe_drive.sqlite3`. Uploads, output recordings, frame logs/manifests and SQLite must survive together. A persistent volume is required for restart/redeploy persistence; the rest of the host filesystem is not a durable artifact store.

Back up SQLite with its online backup API or while the service is stopped, and quiesce writes while copying the matching evidence directories. Encrypt/restrict backups and test restoration. Do not copy an actively written SQLite file as the only backup. A restored database without the matching UUID folders cannot supply recordings. Review retention/licensing before any public sample is published.

Retention cleanup is an offline operator command. Stop the app first, back it up, preview the selected terminal sessions, then optionally apply:

```bash
PYTHONPATH=src .venv/bin/python scripts/demo_admin.py cleanup \
  --data /var/data/safe-drive --database /var/data/safe-drive/safe_drive.sqlite3 --hours 72
# Review the dry-run IDs first. Only then add --apply to delete those sessions/files.
```

It skips active/new sessions, validates UUIDs/path confinement and removes old terminal sessions with cascading tracks/events. There is no anonymous deletion endpoint or background deletion of user evidence. It is not safe to run retention concurrently with an active service. Disk checks stop new work but cannot replace host-level filesystem quotas or a scheduled operator retention policy.

## Exact Render setup (only after approval)

The included `render.yaml` targets a **paid single-instance Python web service with a persistent disk**. It is not applied by committing/pushing this repository. Do not create/sync a Blueprint or click a deploy action until deployment/cost approval is given.

1. In Render, create a Python web service from this repository's `main` branch, or review/import `render.yaml`. Use build command `pip install -e '.[deploy]'`, start command `gunicorn --config gunicorn.conf.py app:app`, health path `/healthz`, one instance. Disable automatic deploys. The Gunicorn config reads the host-provided `PORT` and binds the host interface in production.
2. Attach a persistent disk at `/var/data`; the template specifies 5 GB. This is a paid resource. Set the data/database paths above. Do not rely on an ephemeral/free filesystem for records/evidence.
3. Set `SAFE_DRIVE_ENV=production`, a generated random `SAFE_DRIVE_SECRET`, `SAFE_DRIVE_ALLOWED_HOSTS` to the assigned exact service hostname (and any approved custom hostname), `SAFE_DRIVE_USERS_JSON` with offline-generated hashes, `SAFE_DRIVE_TRUST_PROXY=1` only for Render's trusted TLS proxy, `SAFE_DRIVE_ALLOW_UPLOADS=0`, `SAFE_DRIVE_ENABLE_CAMERAS=0`. Never put these secrets in source or shell-command history. `render.yaml` uses secret generation/unsynced environment values rather than credentials.
4. If desired, provision one licensed, reviewed sample file onto the volume and set its fixed path plus genuine licence attribution. Without it the demo correctly reports that no sample is available; there are no synthetic AI results.
5. **After approval only**, deploy and verify HTTPS: `/healthz` is 200 and contains only status; public session APIs contain no private data; private evidence/mutation APIs require login; secure cookie flags, login/logout/CSRF, operator role restrictions and sample playback work. Test restart persistence and backup restore on the host. Do not enable uploads just because the web UI starts.

Official references: [Render Flask/Gunicorn setup](https://render.com/docs/deploy-flask), [persistent disks and single-instance limits](https://render.com/docs/disks), [Blueprint reference](https://render.com/docs/blueprint-spec), [Gunicorn settings](https://gunicorn.org/reference/settings/).

## Remaining release gates and limitations

- No public deployment, external penetration test, host firewall, browser HTTPS cookie test on a public origin, backup restoration, or production load/DoS test has been performed by this change.
- Real YOLO/appearance inference, codec output, real-footage ID consistency, calibrated field-speed accuracy and camera access require the missing assets/native runtime checks. The synthetic native smoke test timed out during NumPy import; it produced no verified video. Deterministic stub tests are not end-to-end AI validation.
- Public mode has no bundled sample footage; operator-provided licensing/consent is required. An empty public dashboard does not imply that private analyses are empty or safe to publish.
- The application is a controlled demo with a shared operator workspace, short-lived signed sessions and a single-process supervisor. It is not an Internet-scale or multi-tenant surveillance service. Add SSO/MFA, durable task coordination, centralized rate limiting, storage quotas, audited per-resource permissions and hardened worker isolation before broad public processing.
- Helmet inference remains experimental and requires separate compatible trained weights. Approach-risk screening is unvalidated research logic; accident detection is not implemented.

## Verification record (29 October 2026)

- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`: **83 tests passed**, 318.048 seconds, no skips. An initial secure-cookie test failure was fixed before this passing run. A SQLite connection ResourceWarning was subsequently fixed and the two maintenance tests passed again with `-W error::ResourceWarning`.
- `node --test tests/test_ui_core.cjs`: **8 passed**, no failures/skips; rerun after the generic processing-error message fix. The 10 adapter/timestamp tests were also rerun successfully after the uint8-frame validation change.
- `git diff --check` and staged whitespace checks passed. The 43 staged files were reviewed and scanned for private-key/token patterns and forbidden runtime artifacts; none were flagged. This is not a formal penetration test or a guarantee against all secrets/vulnerabilities.
- `.venv/bin/python -m pip check`: no broken requirements. Gunicorn **26.2.0** was installed into the existing environment after the sandboxed PyPI attempt failed DNS resolution; no environment was replaced and the vision stack was not reinstalled.
- The synthetic analytic calibration CLI check mapped a held-out 5 m segment to 4.999999999999999 m. This verifies the analytic fixture only, not a road survey or real speed accuracy.
- Real detector/appearance inference was not run: licensed compatible detector weights and traffic footage are absent. Native codec/tracker smoke testing timed out during NumPy import and produced no verified output video.
- No successful Gunicorn HTTP response was observed in this environment. The elevated loopback HTTP probe and a subsequent WSGI restart were not executed because automatic approval review reported its selected model at capacity. WSGI/host HTTP verification remains a release gate; the successful Flask test-client checks do not substitute for it. No deployment or charges occurred.
