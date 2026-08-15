# UniFi Protect Camera Privacy Toggle

A lightweight admin tool for selectively disabling/enabling UniFi Protect cameras via the local API — designed for scenarios like temporarily converting offices to changing rooms.

## Components

| File | Purpose |
|---|---|
| `app.py` | Flask web UI — toggle individual cameras on/off with group-based URL routing |
| `ensure_all_on.py` | Cron safety net — re-enables every camera across all groups |
| `protect_api.py` | Shared UniFi Protect API client with group filtering |
| `config.py` | Connection settings, camera groups, default recording mode |
| `requirements.txt` | Python dependencies |
| `camera-toggle.service` | systemd service definition |
| `camera-ensure-all-on.service` | One-shot nightly safety service |
| `camera-ensure-all-on.timer` | 11:00 PM America/Chicago schedule |

## Quick Start

```bash
cd /opt/unifi-camera-toggle
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.py config.py
chmod 600 config.py
nano config.py          # Fill in controller credentials and camera groups
python app.py           # → http://your-server:5000
```

## Configuration

Copy `config.example.py` to `config.py` and edit:

```python
PROTECT_HOST = "protect.example.local"
PROTECT_USERNAME = "local-admin"
PROTECT_PASSWORD = "your-password"
VERIFY_SSL = False
API_BASE = "/proxy/protect/api"
```

> **Important:** You need a **local** admin account on the controller.
> Ubiquiti SSO / cloud accounts won't work with the local API.

## Camera Groups

Groups let different administrators see different camera sets via URL paths:

```python
CAMERA_GROUPS = {
    "default": ["Office A", "Office B", "Conference Room"],
    "bob": ["Office A", "Office B"],
    "alice": ["Conference Room"],
}
```

- `http://<ip>:5000/` → shows the "default" group
- `http://<ip>:5000/bob` → shows only Bob's cameras
- `http://<ip>:5000/alice` → shows only Alice's cameras

Groups filter the view only — the toggle API works on any camera regardless
of group. An empty list shows all cameras. Non-default groups display a blue
badge on the page title.

## Optional Client Device Lookup

Set `UNIFI_NETWORK` in `config.py` to a dictionary containing `host`,
`username`, `password`, and `verify_ssl` to resolve audit-log client IPs using
the UniFi Network controller. Leave it as `None` to use local name-resolution
methods and an IP fallback.

## How "Off" Works

When you toggle a camera **off**, the tool sets its recording mode to `never`
and enables a full-frame privacy zone (blacking out the live view):

- No footage is recorded
- Live view shows a black/privacy screen
- The camera hardware stays powered (instant restoration, no reboot)

Toggling **on** restores the original recording mode and removes the privacy zone.

## Scheduled Safety Net

The `ensure_all_on.py` script re-enables all cameras across all groups. Preview
it before enabling the timer:

```bash
cd /opt/unifi-camera-toggle
.venv/bin/python3 ensure_all_on.py --dry-run
```

`camera-ensure-all-on.timer` runs the one-shot service every night at 11:00 PM
in `America/Chicago`, including across daylight-saving transitions. `Persistent`
causes a missed run to execute after the server returns.

```bash
sudo systemctl enable --now camera-ensure-all-on.timer
systemctl list-timers camera-ensure-all-on.timer
sudo journalctl -u camera-ensure-all-on.service --since today
```

## Admin Portal Integration

This service is also accessible via the unified Admin Portal on port 8080
(Cameras tab), which shows all cameras unfiltered. The `/api/list` endpoint
provides JSON data for portal integration.

## Security Notes

- Run on the **management VLAN only** — do not expose to the internet.
- Credentials are in `config.py` — protect with `chmod 600`.
- Audit entries are written to `/var/log/unifi-camera-audit.log`; keep that
  file at mode `0600` when the services share an account. Scheduled safety-job
  output is retained by journald.
- The Flask dev server is fine for light internal use; for heavier loads,
  use Gunicorn + nginx with HTTPS.

## Systemd Service

```bash
sudo systemctl status camera-toggle
sudo systemctl restart camera-toggle
sudo journalctl -u camera-toggle --since today
```
