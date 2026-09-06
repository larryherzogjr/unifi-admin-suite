# UniFi Admin Suite

A five-service physical security management platform for UniFi infrastructure,
built as a capstone project for the M.S. in Business Information Systems at
Valley City State University.

## Services

| Service | Port | Purpose |
|---|---:|---|
| Camera Privacy Toggle | 5000 | Selectively disable and enable cameras for privacy |
| Door Lock Toggle | 5001 | Temporarily unlock and lock doors |
| Hardware Monitor | 5002 | Real-time device health and email alerts |
| Audit Viewer | 5004 | Searchable camera and door action history |
| Admin Portal | 8080 | Unified dashboard for all four backend services |

## Technology

- Python 3.9 or newer
- Flask with inline Jinja templates and vanilla HTML, CSS, and JavaScript
- Requests and urllib3 for UniFi controller communication
- systemd for long-running services and scheduled safety jobs

There is no separate frontend toolchain or build step. Shared UI assets are maintained
in `ui/` and copied into each service’s `static/` directory with
`python ui/sync_assets.py`. Deploy `static/` alongside each service’s `app.py`.
See [UI maintenance and verification](ui/README.md).

## Setup

Each service has its own directory, virtual environment, `requirements.txt`,
and `config.example.py`:

```bash
cd <service-directory>
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.py config.py
chmod 600 config.py
python app.py
```

Configure and start the four backend services before the Admin Portal. The
Portal expects the Camera, Door, Monitor, and Audit services on localhost.

Use the camera and door safety scripts with `--dry-run` before enabling their
systemd timers:

```bash
python camera-toggle/ensure_all_on.py --dry-run
python door-lock-toggle/ensure_all_locked.py --dry-run
```

See the README in each service directory for controller credentials, service
management, cron, and security details. Keep the suite on a management network
and never commit a populated `config.py`.

The committed systemd units use the production `/opt/unifi-*` paths and the
`lherzog` service account. Adjust `User`, `WorkingDirectory`, and `ExecStart`
before installing them on a different host.

## Author

Larry Herzog Jr. — March 2026
