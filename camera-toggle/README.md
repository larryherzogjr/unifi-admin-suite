# UniFi Protect Camera Toggle

A lightweight admin tool for selectively disabling/enabling UniFi Protect cameras via the local API — designed for scenarios like temporarily converting offices to changing rooms.

## Components

| File | Purpose |
|---|---|
| `app.py` | Flask web UI — toggle individual cameras on/off |
| `ensure_all_on.py` | Cron safety net — re-enables every camera |
| `protect_api.py` | Shared UniFi Protect API client |
| `config.py` | Connection settings (edit this first) |
| `requirements.txt` | Python dependencies |

## Quick Start

```bash
# 1. Clone / copy files to your server
# 2. Install dependencies
pip install -r requirements.txt

# 3. Edit config.py with your controller details
nano config.py

# 4. Run the web UI
python app.py
# → http://your-server:5000
```

## Configuration

Edit `config.py`:

```python
PROTECT_HOST = "192.168.1.1"       # Your UDM Pro / UNVR / Cloud Key IP
PROTECT_USERNAME = "local-admin"    # Local admin account (NOT Ubiquiti SSO)
PROTECT_PASSWORD = "your-password"
VERIFY_SSL = False                  # Self-signed cert on most controllers
```

> **Important:** You need a **local** admin account on the controller.
> Ubiquiti SSO / cloud accounts won't work with the local API.
> Create one under OS Settings → Admins → Add Admin → Local.

## How "Off" Works

When you toggle a camera **off**, the tool sets its recording mode to `never`
and enables a full-frame privacy zone (blacking out the live view). This means:

- No footage is recorded
- Live view shows a black/privacy screen
- The camera hardware stays powered (no physical reboot needed to restore)

Toggling **on** restores the original recording mode and removes the privacy zone.

## Cron Safety Net

The `ensure_all_on.py` script re-enables all cameras. Schedule it as a nightly
catch-all so nothing stays off accidentally:

```bash
# Run every night at 11 PM
0 23 * * * /usr/bin/python3 /path/to/unifi-camera-toggle/ensure_all_on.py >> /var/log/camera-ensure.log 2>&1
```

## API Compatibility

Tested against UniFi Protect on:
- UDM Pro / UDM SE (API path: `/proxy/protect/api/`)
- UNVR / Cloud Key Gen2+ (API path: `/api/` — toggle `API_BASE` in config if needed)

The tool auto-detects the API base path, but you can override it in `config.py`
if auto-detection doesn't work for your setup.

## Security Notes

- Run this on your **management VLAN only** — do not expose to the internet.
- The Flask dev server is fine for light internal use; for anything heavier,
  put it behind Gunicorn + nginx with HTTPS.
- Credentials are stored in `config.py` — protect file permissions accordingly
  (`chmod 600 config.py`).
