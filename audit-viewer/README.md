# UniFi Audit Log Viewer

A read-only Flask dashboard that combines the Camera Privacy Toggle and Door
Lock Toggle JSON-lines audit logs into a searchable action history. It listens
on port 5004 and supplies summary data to the Admin Portal.

## Components

| File | Purpose |
|---|---|
| `app.py` | Audit-log reader, dashboard, filtering, and `/api/list` endpoint |
| `config.py` | Log paths, default date range, and Flask settings |
| `requirements.txt` | Python dependencies |
| `audit-viewer.service` | systemd service definition |

## Quick Start

```bash
cd /opt/unifi-audit-viewer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.py config.py
chmod 600 config.py
python app.py           # http://your-server:5004
```

## Configuration

```python
CAMERA_AUDIT_LOG = "/var/log/unifi-camera-audit.log"
ACCESS_AUDIT_LOG = "/var/log/unifi-access-audit.log"
DEFAULT_DAYS = 7

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5004
FLASK_DEBUG = False
```

The Audit Viewer must run as a user that can read both audit logs. In the
standard deployment, all services run as `lherzog`, so the logs can remain
owner-only (`0600`). Audit entries may contain client IPs, device names,
hostnames, user agents, reasons, and physical-security actions.

Malformed JSON lines are skipped and logged as warnings. The source log files
are never modified by this service.

## Admin Portal Integration

Set the following in the Portal configuration:

```python
AUDIT_BACKEND = "http://127.0.0.1:5004"
```

The `/api/list` endpoint returns entry counts and the ten most recent actions.

## Systemd

```bash
sudo systemctl status audit-viewer
sudo systemctl restart audit-viewer
sudo journalctl -u audit-viewer --since today
```

## Security

- Run on the management VLAN only.
- Keep both audit logs at mode `0600` when all services share an account, or
  use a dedicated group with mode `0640`.
- Do not expose the dashboard directly to the internet.
