# UniFi Access Door Lock Toggle

A lightweight admin tool for selectively unlocking/locking UniFi Access doors via the developer API — designed for scenarios like temporarily propping doors open during events or maintenance, with an automated nightly safety net to ensure all doors are locked.

## Components

| File | Purpose |
|---|---|
| `app.py` | Flask web UI — toggle individual doors locked/unlocked |
| `ensure_all_locked.py` | Cron safety net — re-locks every managed door |
| `access_api.py` | Shared UniFi Access developer API client |
| `config.py` | Connection settings (edit this first) |
| `requirements.txt` | Python dependencies |

## Quick Start

```bash
# 1. Clone / copy files to your server
# 2. Install dependencies
cd /opt/unifi-access
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Edit config.py with your controller details
nano config.py

# 4. Run the web UI
python app.py
# → http://your-server:5001
```

## Configuration

Edit `config.py`:

```python
ACCESS_HOST = "protect.se-test.org"   # Your UNVR / UDM IP or hostname
ACCESS_PORT = 12445                    # UniFi Access API port
API_TOKEN = "your-bearer-token-here"   # Developer API token from Access settings
VERIFY_SSL = False                     # Self-signed cert on most controllers
```

> **Generating an API token:** In the UniFi Access application, navigate to
> Settings → System → scroll to "API Token" and generate one.

## How Unlock Works

When you toggle a door to **unlocked**, the tool sets the lock rule to
`keep_open`, which holds the door in an unlocked state until explicitly
changed. The door will remain unlocked indefinitely (no timeout).

Toggling back to **locked** sends a `lock_now` command, immediately
re-engaging the lock and returning to the door's normal access policy.

## Cron Safety Net

The `ensure_all_locked.py` script re-locks all managed doors. Schedule it
as a nightly catch-all:

```bash
# Run every night at 11 PM
0 23 * * * /opt/unifi-access/.venv/bin/python3 /opt/unifi-access/ensure_all_locked.py >> /var/log/unifi-access-ensure.log 2>&1
```

## API Compatibility

Uses the official UniFi Access Developer API (port 12445) with Bearer
token authentication. This is a documented, supported API — more stable
than the undocumented Protect API.

## Security Notes

- Run this on your **management VLAN only** — do not expose to the internet.
- The API token has full door control permissions — protect `config.py`
  accordingly (`chmod 600 config.py`).
- For production hardening, place Flask behind Gunicorn + nginx with HTTPS.
