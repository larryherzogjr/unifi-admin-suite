# UniFi Admin Portal

A unified web dashboard that combines the Camera Privacy Toggle, Door Lock
Toggle, and Hardware Monitor under a single tabbed interface. Runs as a thin
proxy layer on port 8080, routing to the three independent backend services.

## Components

| File | Purpose |
|---|---|
| `app.py` | Flask proxy app — tabbed UI, API routing, backend data fetching |
| `config.py` | Backend URLs and Flask settings |
| `requirements.txt` | Python dependencies |

## Architecture

The portal does **not** talk to the UniFi controllers directly. It proxies
all requests through the three backend Flask apps:

| Tab | Backend | Port | Function |
|---|---|---|---|
| Cameras | Camera Privacy Toggle | 5000 | Toggle camera privacy mode on/off |
| Doors | Door Lock Toggle | 5001 | Unlock/lock doors temporarily |
| Monitor | Hardware Monitor | 5002 | Real-time device health overview |

If one backend is down, its tab shows an error message while the other tabs
continue to work normally.

## Quick Start

```bash
cd /opt/unifi-admin-portal
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
nano config.py
python app.py           # → http://your-server:8080
```

## Configuration

Copy `config.example.py` to `config.py` and edit:

```python
CAMERA_BACKEND = "http://127.0.0.1:5000"
DOOR_BACKEND = "http://127.0.0.1:5001"
MONITOR_BACKEND = "http://127.0.0.1:5002"

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 8080
```

## Features

- **Three tabs:** Cameras, Doors, Monitor — each with count badges
- **Alert badges:** Red highlight when cameras are off, doors are unlocked,
  or devices are down
- **Tab persistence:** Active tab saved in URL hash (#cameras, #doors, #monitor)
  so it survives page refreshes
- **Inline updates:** Toggle switches update badges and card borders without
  page reload
- **Independent failure domains:** Each backend can fail independently without
  affecting the other tabs
- **Full Dashboard link:** Monitor tab includes a link to the standalone
  hardware monitor on port 5002 for detailed CPU/memory/temp metrics

## Prerequisites

All three backend services must be running and must have the `/api/list`
endpoint available:

- Camera Privacy Toggle on port 5000
- Door Lock Toggle on port 5001
- Hardware Monitor on port 5002

## Systemd Service

```bash
sudo systemctl status unifi-admin-portal
sudo systemctl restart unifi-admin-portal
sudo journalctl -u unifi-admin-portal --since today
```

The service is configured to start after all three backend services:

```ini
After=network-online.target camera-toggle.service door-lock-toggle.service unifi-monitor.service
```

## Restarting All Services

```bash
sudo systemctl restart camera-toggle door-lock-toggle unifi-monitor unifi-admin-portal
```

## Security Notes

- Run on the **management VLAN only**.
- No credentials are stored in this service — all sensitive communication
  happens between the backends and the controllers.
- Inter-service communication is on localhost (127.0.0.1) only.
