# UniFi Access Door Lock Toggle

A lightweight admin tool for selectively unlocking/locking UniFi Access doors via the developer API — designed for scenarios like temporarily propping doors open during events or maintenance, with an automated nightly safety net.

## Components

| File | Purpose |
|---|---|
| `app.py` | Flask web UI, durable deadline sweeper, cache, and button API |
| `state_store.py` | SQLite timed-unlock and idempotency repository |
| `ensure_all_locked.py` | Nightly reconciler for unexpected unlocks |
| `access_api.py` | Shared UniFi Access developer API client |
| `config.py` | Connection settings, door inclusion list, retry parameters |
| `requirements.txt` | Python dependencies |
| `door-lock-toggle.service` | systemd service definition |
| `door-ensure-all-locked.service` | One-shot nightly safety service |
| `door-ensure-all-locked.timer` | 7:00 PM America/Chicago schedule |

## Quick Start

```bash
cd /opt/unifi-access
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.py config.py
chmod 600 config.py
sudo install -d -o lherzog -g lherzog -m 0700 /var/lib/unifi-access
nano config.py          # Fill in controller details and API token
python app.py           # → http://your-server:5001
```

## Configuration

Copy `config.example.py` to `config.py` and edit:

```python
ACCESS_HOST = "access.example.local"
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

## Optional Client Device Lookup

Set `UNIFI_NETWORK` in `config.py` to a dictionary containing `host`,
`username`, `password`, and `verify_ssl` to resolve audit-log client IPs using
the UniFi Network controller. Leave it as `None` to use local name-resolution
methods and an IP fallback.

## How Lock/Unlock Works

- **Unlock:** Sets the lock rule to `keep_unlock`, holding the door open
  until explicitly changed.
- **Lock:** Sends `lock_now`, immediately re-engaging the lock and returning
  to the door's normal access policy.

The API reports status via `door_lock_relay_status`: `"unlock"` when open,
`"lock"` when locked.

## Durable Timed Unlocks

Timed unlock deadlines are stored in SQLite rather than process memory. A
single background sweeper retries overdue locks until UniFi confirms the relay
is locked; rows are never discarded merely because a controller request fails.
On restart, overdue rows are enforced during startup and future deadlines
resume automatically.

The database defaults to `/var/lib/unifi-access/door_state.db` and must be
owner-only. It is also used by the nightly safety service. The committed
systemd units create that directory as the service account with mode `0700`;
the manual `install -d` step is only needed when running outside systemd.

## Physical Button API

Button access is disabled until `BUTTON_DEVICES` contains a token and an
explicit list of allowed UniFi door UUIDs. The unlock duration is fixed by
`BUTTON_UNLOCK_MINUTES` (180 minutes in the example).

```text
GET  /api/button/v1/state?door_id=<uuid>
POST /api/button/v1/toggle
Authorization: Bearer <device-token>
```

The toggle body contains only `door_id`, a UUID `request_id`, and optionally
`duration_min: 180`. The server reads the live relay state and chooses the
direction atomically. Completed request IDs are retained for 24 hours so a
network retry replays the result instead of toggling twice.

State polling is served from a five-second controller cache. Responses older
than 30 seconds are rejected with HTTP 503 so a button cannot display stale
state as authoritative.

## Tests

The backend tests are offline and use a simulated UniFi Access controller:

```bash
cd /opt/unifi-access
.venv/bin/python3 -m unittest discover -s tests -v
```

They cover durable restart recovery, authenticated and door-scoped button
requests, idempotent replay, concurrent-operation rejection, command-response
loss, stale cache handling, retrying deadline enforcement, and 7:00 PM safety
reconciliation.

## Scheduled Safety Net

Preview the safety script before enabling its timer:

```bash
cd /opt/unifi-access
.venv/bin/python3 ensure_all_locked.py --dry-run
```

`door-ensure-all-locked.timer` runs the one-shot service every night at 7:00 PM
in `America/Chicago`, including across daylight-saving transitions. `Persistent`
causes a missed run to execute after the server returns. A valid, unexpired
durable timed unlock is preserved; unlocked doors without one are locked.

```bash
sudo systemctl enable --now door-ensure-all-locked.timer
systemctl list-timers door-ensure-all-locked.timer
sudo journalctl -u door-ensure-all-locked.service --since today
```

## Admin Portal Integration

This service is also accessible via the unified Admin Portal on port 8080
(Doors tab). The `/api/list` endpoint provides JSON data for portal integration.

## API Compatibility

Uses the official UniFi Access Developer API (port 12445) with Bearer token
authentication. This is a documented, supported API.

## Security Notes

- Run on the **management VLAN only**.
- The API token grants full door control — protect `config.py` with `chmod 600`.
- Button tokens are compared in constant time and restricted to configured door
  UUIDs. The existing human web routes remain unauthenticated in this milestone;
  keep port 5001 restricted to the management network and terminate TLS at the
  internal reverse proxy before connecting hardware.
- Audit entries are written to `/var/log/unifi-access-audit.log`; keep that
  file at mode `0600` when the services share an account. Scheduled safety-job
  output is retained by journald.
- For production hardening, place Flask behind Gunicorn + nginx with HTTPS.

## Systemd Service

```bash
sudo systemctl status door-lock-toggle
sudo systemctl restart door-lock-toggle
sudo journalctl -u door-lock-toggle --since today
```
