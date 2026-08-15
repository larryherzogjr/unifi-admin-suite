# UniFi Admin Portal

A unified Flask dashboard for the Camera Privacy Toggle, Door Lock Toggle,
Hardware Monitor, and Audit Viewer. It runs as a thin proxy on port 8080 and
keeps each backend as an independent service.

## Components

| File | Purpose |
|---|---|
| `app.py` | Tabbed UI, API routing, and backend data fetching |
| `config.py` | Backend URLs and Flask settings |
| `requirements.txt` | Python dependencies |
| `unifi-admin-portal.service` | systemd service definition |

## Architecture

The Portal does not communicate with UniFi controllers or audit files
directly. It proxies four local Flask backends:

| Tab | Backend | Port | Function |
|---|---|---:|---|
| Cameras | Camera Privacy Toggle | 5000 | Toggle camera privacy mode |
| Doors | Door Lock Toggle | 5001 | Temporarily unlock or lock doors |
| Monitor | Hardware Monitor | 5002 | Show UniFi hardware health |
| Audit | Audit Viewer | 5004 | Show recent camera and door actions |

If one backend is unavailable, its tab reports an error while the others
continue to work.

## Quick Start

```bash
cd /opt/unifi-admin-portal
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.py config.py
chmod 600 config.py
python app.py           # http://your-server:8080
```

## Configuration

```python
CAMERA_BACKEND = "http://127.0.0.1:5000"
DOOR_BACKEND = "http://127.0.0.1:5001"
MONITOR_BACKEND = "http://127.0.0.1:5002"
AUDIT_BACKEND = "http://127.0.0.1:5004"

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 8080
FLASK_DEBUG = False
```

## Prerequisites

All four backends should be running and expose `/api/list`:

- Camera Privacy Toggle on port 5000
- Door Lock Toggle on port 5001
- Hardware Monitor on port 5002
- Audit Viewer on port 5004

## Features

- Camera, Door, Monitor, and Audit tabs with status badges
- Timed camera privacy and door unlock actions
- Camera enable-all and door lock-all safety actions
- Inline state updates without a full page reload
- Active-tab persistence through the URL hash
- Independent backend failure handling
- Full-dashboard links for Monitor and Audit details

## Systemd

Install the committed unit under `/etc/systemd/system`, then enable it using
the normal systemd workflow. Its startup ordering includes all four backends:

```ini
After=network-online.target camera-toggle.service door-lock-toggle.service unifi-monitor.service audit-viewer.service
```

Common operations:

```bash
sudo systemctl status unifi-admin-portal
sudo systemctl restart unifi-admin-portal
sudo journalctl -u unifi-admin-portal --since today
sudo systemctl restart camera-toggle door-lock-toggle unifi-monitor audit-viewer unifi-admin-portal
```

## Security

- Run the Portal on the management VLAN only.
- Keep backend traffic on `127.0.0.1`.
- Protect `config.py` with mode `0600` even though it contains backend URLs
  rather than controller credentials.
- The built-in Flask server is intended for light internal use. Use a hardened
  WSGI deployment and HTTPS if the service crosses trust boundaries.
