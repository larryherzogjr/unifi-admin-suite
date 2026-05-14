"""
Audit logging helper — writes JSON lines to a dedicated log file.

Each entry includes:
  - timestamp (ISO 8601)
  - action (camera_off, camera_on, timed_off, cancel_timer, enable_all, etc.)
  - target (camera/door name)
  - reason (freeform text or empty)
  - duration_min (for timed actions, or null)
  - client_ip
  - client_host (reverse DNS or IP if lookup fails)
  - client_ua (User-Agent string)
"""

import json
import socket
import logging
from datetime import datetime
from flask import request

log = logging.getLogger("audit")

_audit_file = None


def init(filepath: str):
    """Set the audit log file path."""
    global _audit_file
    _audit_file = filepath
    log.info("Audit log: %s", filepath)


def write(action: str, target: str, reason: str = "", duration_min: int = None):
    """Write an audit entry."""
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
    client_ua = request.headers.get("User-Agent", "unknown")

    # Attempt reverse DNS
    try:
        client_host = socket.gethostbyaddr(client_ip.split(",")[0].strip())[0]
    except Exception:
        client_host = client_ip

    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "target": target,
        "reason": reason or "",
        "duration_min": duration_min,
        "client_ip": client_ip,
        "client_host": client_host,
        "client_ua": client_ua,
    }

    log.info("AUDIT: %s %s by %s (%s) reason=%r",
             action, target, client_ip, client_host, reason)

    if _audit_file:
        try:
            with open(_audit_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            log.exception("Failed to write audit log to %s", _audit_file)
