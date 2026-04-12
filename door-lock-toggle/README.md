# UniFi Access Door Lock Toggle

A lightweight admin tool for selectively unlocking/locking UniFi Access doors via the developer API — designed for scenarios like temporarily propping doors open during events or maintenance, with an automated nightly safety net.

## Components

| File | Purpose |
|---|---|
| `app.py` | Flask web UI — toggle individual doors locked/unlocked |
| `ensure_all_locked.py` | Cron safety net — re-locks every managed door |
| `access_api.py` | Shared UniFi Access developer API client |
| `config.py` | Connection settings, door inclusion list, retry parameters |
| `requirements.txt` | Python dependencies |

## Quick Start

```bash
cd /opt/unifi-access
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
nano config.py          # Fill in controller details and API token
python app.py           # → http://your-server:5001
```

## Configuration

Copy `config.example.py` to `config.py` and edit:

```python
ACCESS_HOST = "protect.se-test.org"
ACCESS_PORT = 12445
API_TOKEN = "your-bearer-token-here"
VERIFY_SSL = False
```

> **Generating an API token:** In the UniFi Access application, navigate to
> Settings → System → API Token and generate one.

## Door Inclusion List

Only doors in the inclusion list appear in the dashboard:

```python
INCLUDED_DOORS = [
    "Door Access Hub",
]
```

Empty list = show all doors. Names are case-insensitive.

## How Lock/Unlock Works

- **Unlock:** Sets the lock rule to `keep_unlock`, holding the door open
  until explicitly changed.
- **Lock:** Sends `lock_now`, immediately re-engaging the lock and returning
  to the door's normal access policy.

The API reports status via `door_lock_relay_status`: `"unlock"` when open,
`"lock"` when locked.

## Cron Safety Net

```bash
# Run every evening at 7 PM
0 19 * * * /opt/unifi-access/.venv/bin/python3 /opt/unifi-access/ensure_all_locked.py >> /var/log/unifi-access-ensure.log 2>&1
```

Supports `--dry-run` to preview without changes.

## Admin Portal Integration

This service is also accessible via the unified Admin Portal on port 8080
(Doors tab). The `/api/list` endpoint provides JSON data for portal integration.

## API Compatibility

Uses the official UniFi Access Developer API (port 12445) with Bearer token
authentication. This is a documented, supported API.

## Security Notes

- Run on the **management VLAN only**.
- The API token grants full door control — protect `config.py` with `chmod 600`.
- For production hardening, place Flask behind Gunicorn + nginx with HTTPS.

## Systemd Service

```bash
sudo systemctl status door-lock-toggle
sudo systemctl restart door-lock-toggle
sudo journalctl -u door-lock-toggle --since today
```
