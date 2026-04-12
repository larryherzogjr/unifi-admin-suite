# UniFi Hardware Monitor

Real-time hardware health dashboard for your entire UniFi stack — cameras,
NVR, door access hubs, access points, switches, and Cloud Key. Includes
email alerting on device status changes.

## Components

| File | Purpose |
|---|---|
| `app.py` | Flask web dashboard with background polling thread |
| `collectors.py` | Three API collectors (Protect, Access, Network) |
| `alerter.py` | Email alerting with per-device cooldown |
| `config.py` | API connections, SMTP settings, poll interval, exclusions |
| `requirements.txt` | Python dependencies |

## Data Sources

| Source | Host | Auth | Devices |
|---|---|---|---|
| Protect API | UNVR Pro | Session cookie + CSRF | Cameras + NVR (CPU, mem, temp, storage) |
| Access API | UNVR Pro :12445 | Bearer token | Door access hubs |
| Network API | Cloud Key Gen2+ | Session cookie + CSRF | APs, switches, Cloud Key (CPU, mem, temp) |

## Quick Start

```bash
cd /opt/unifi-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
nano config.py          # Fill in all three API connections + email settings
python app.py           # → http://your-server:5002
```

## Configuration

Copy `config.example.py` to `config.py` and edit. Key settings:

```python
# Protect (UNVR Pro)
PROTECT_HOST = "protect.se-test.org"
PROTECT_USERNAME = "local-admin"
PROTECT_PASSWORD = "changeme"

# Access (same UNVR Pro, port 12445)
ACCESS_TOKEN = "your-bearer-token"

# Network (Cloud Key Gen2+)
NETWORK_HOST = "10.42.42.7"
NETWORK_USERNAME = "local-admin"
NETWORK_PASSWORD = "changeme"

# Email alerts
SMTP_ENABLED = False          # Set True after configuring Gmail app password
SMTP_USERNAME = "you@gmail.com"
SMTP_PASSWORD = ""            # Gmail app password (16 chars)
ALERT_TO = ["you@gmail.com"]

# Tuning
POLL_INTERVAL = 120           # Seconds between API checks
ALERT_COOLDOWN = 3600         # Seconds before re-alerting same device

# Device exclusions
EXCLUDED_DEVICES = []         # Hide specific devices by name (case-insensitive)
```

## Features

- **Online/offline status** with pulsing red indicator for down devices
- **CPU, memory, temperature** with color-coded progress bars (green/amber/red)
- **Firmware versions** and **uptime** for all devices
- **NVR storage** utilization
- **Device type filtering** (Camera, NVR, Switch, AP, etc.)
- **Auto-refresh** every 30 seconds from cached data
- **Background polling** every 2 minutes (configurable)
- **Email alerts** on status transitions with 1-hour cooldown per device
- **Exclusion list** to hide noisy or non-critical devices
- **Portal integration** as a third tab on port 8080

## Email Alerts

1. Enable 2-Step Verification on your Google account
2. Generate an App Password: myaccount.google.com → Security → App passwords
3. Update config.py with your Gmail address and app password
4. Set `SMTP_ENABLED = True`
5. Restart the service

Alert behavior:
- **Device Down:** Fires when a device goes from online to offline
- **Recovery:** Fires when a device comes back online
- **Cooldown:** 1-hour window per device to prevent alert fatigue
- **First run:** No alerts on first poll after restart (establishes baseline)
- **Batching:** Multiple changes in one poll cycle = one email

### Test Email

```bash
cd /opt/unifi-monitor
.venv/bin/python3 -c "
import config, smtplib
from email.mime.text import MIMEText
msg = MIMEText('Test alert from UniFi Hardware Monitor.')
msg['From'] = config.ALERT_FROM
msg['To'] = ', '.join(config.ALERT_TO)
msg['Subject'] = f'{config.ALERT_SUBJECT_PREFIX} Test Alert'
with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as s:
    s.starttls()
    s.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
    s.sendmail(config.ALERT_FROM, config.ALERT_TO, msg.as_string())
    print('Test email sent!')
"
```

## Admin Portal Integration

This service is accessible via the unified Admin Portal on port 8080
(Monitor tab), which shows a summary device list with a "Full Dashboard"
link to port 5002. The `/api/list` endpoint provides JSON data for
portal integration.

## Security Notes

- Run on the **management VLAN only**.
- Config file contains credentials for three controllers + Gmail — protect
  with `chmod 600`.
- This service is **read-only** — it does not modify any device settings.
- The Gmail SMTP connection is the only outbound traffic leaving the LAN.

## Systemd Service

```bash
sudo systemctl status unifi-monitor
sudo systemctl restart unifi-monitor
sudo journalctl -u unifi-monitor --since today
```
