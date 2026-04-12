"""
Email alerting for device status changes.

Sends alerts when devices go offline or come back online.
Respects a cooldown window to avoid alert fatigue.
"""

import time
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import config

log = logging.getLogger("alerter")

# Track last alert time per device key to enforce cooldown
_last_alert: dict[str, float] = {}

# Track previous status per device to detect transitions
_prev_status: dict[str, str] = {}


def _device_key(device: dict) -> str:
    """Unique key for a device based on source + name."""
    return f"{device.get('source', '?')}:{device.get('name', '?')}"


def check_and_alert(snapshot: dict):
    """
    Compare current device statuses against previous snapshot.
    Send email alerts for status transitions (online→offline, offline→online).
    """
    if not config.SMTP_ENABLED:
        return

    now = time.time()
    alerts = []

    for device in snapshot.get("devices", []):
        key = _device_key(device)
        current = device.get("status", "unknown")
        previous = _prev_status.get(key)

        # Update stored status
        _prev_status[key] = current

        # Skip if no previous status (first run)
        if previous is None:
            continue

        # Detect transition
        if previous != current and current in ("offline", "unreachable"):
            # Device went down
            if _cooldown_ok(key, now):
                alerts.append({
                    "device": device,
                    "transition": f"{previous} → {current}",
                    "severity": "critical",
                })
                _last_alert[key] = now
        elif previous in ("offline", "unreachable") and current == "online":
            # Device recovered
            if _cooldown_ok(key, now):
                alerts.append({
                    "device": device,
                    "transition": f"{previous} → {current}",
                    "severity": "recovery",
                })
                _last_alert[key] = now

    if alerts:
        _send_alert_email(alerts)


def _cooldown_ok(key: str, now: float) -> bool:
    """Check if enough time has passed since the last alert for this device."""
    last = _last_alert.get(key, 0)
    return (now - last) >= config.ALERT_COOLDOWN


def _send_alert_email(alerts: list[dict]):
    """Send a single email covering all current alerts."""
    try:
        subject_parts = []
        body_lines = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for alert in alerts:
            dev = alert["device"]
            name = dev.get("name", "Unknown")
            dev_type = dev.get("type", "")
            ip = dev.get("ip", "")
            transition = alert["transition"]
            severity = alert["severity"]

            icon = "\u26a0\ufe0f" if severity == "critical" else "\u2705"
            subject_parts.append(f"{name} {transition}")

            body_lines.append(f"{icon} {dev_type}: {name}")
            body_lines.append(f"   Status: {transition}")
            if ip:
                body_lines.append(f"   IP: {ip}")
            body_lines.append("")

        subject = f"{config.ALERT_SUBJECT_PREFIX} {', '.join(subject_parts)}"
        body = f"UniFi Hardware Monitor Alert\n{'=' * 40}\nTime: {timestamp}\n\n" + "\n".join(body_lines)

        msg = MIMEMultipart()
        msg["From"] = config.ALERT_FROM
        msg["To"] = ", ".join(config.ALERT_TO)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.sendmail(config.ALERT_FROM, config.ALERT_TO, msg.as_string())

        log.info("Alert email sent: %s", subject)

    except Exception:
        log.exception("Failed to send alert email")


def get_alert_status() -> dict:
    """Return current alert tracking state for the dashboard."""
    return {
        "enabled": config.SMTP_ENABLED,
        "tracked_devices": len(_prev_status),
        "alerts_sent": len(_last_alert),
        "cooldown_seconds": config.ALERT_COOLDOWN,
    }
