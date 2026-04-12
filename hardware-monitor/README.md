# UniFi Hardware Monitor

Real-time hardware health dashboard for your entire UniFi stack — cameras,
NVR, door access hubs, access points, switches, and Cloud Key. Includes
email alerting on status changes.

## Data Sources

| Source | Host | Auth | Devices |
|---|---|---|---|
| Protect API | UNVR Pro | Session cookie | Cameras + NVR system stats |
| Access API | UNVR Pro :12445 | Bearer token | Door access hubs |
| Network API | Cloud Key Gen2+ | Session cookie | APs, switches, gateway |

## Features

- Online/offline status with pulsing indicator for down devices
- CPU, memory, temperature with color-coded progress bars
- Firmware versions and uptime for all devices
- Device type filtering
- Auto-refresh every 30 seconds (dashboard) + configurable background poll
- Email alerts on device status transitions (offline/online) with cooldown
- Portal integration as a third tab on port 8080

## Quick Start

```bash
cd /opt/unifi-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
nano config.py          # Fill in credentials + email settings
python app.py           # → http://your-server:5002
```

## Email Alerts

1. Enable 2-Step Verification on your Google account
2. Generate an App Password: myaccount.google.com → Security → App passwords
3. Update config.py with your Gmail address and app password
4. Set SMTP_ENABLED = True
5. Restart the service

Alerts fire on transitions (online→offline, offline→online) with a
configurable cooldown (default: 1 hour) to prevent alert fatigue.

## Portal Integration

See PORTAL_PATCH.md for instructions on adding a Monitor tab to the
Admin Portal on port 8080.
