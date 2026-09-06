"""
UniFi Admin Portal — unified front-end for Camera Privacy Toggle,
Door Lock Toggle, and Hardware Monitor.

Proxies API calls to three independent backend services running
on ports 5000 (cameras), 5001 (doors), and 5002 (monitor).

Run:  python app.py
Then visit http://your-server:8080
"""

import logging
import requests
from flask import Flask, render_template_string, request, jsonify

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("portal")

app = Flask(__name__)

BACKEND_TIMEOUT = 10

# -------------------------------------------------------------------------
# Backend helpers
# -------------------------------------------------------------------------

def _proxy_get(backend: str, path: str) -> dict | list | None:
    """GET from a backend service and return parsed JSON, or None on error."""
    try:
        r = requests.get(f"{backend}{path}", timeout=BACKEND_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("Backend GET %s%s failed: %s", backend, path, exc)
        return None


def _proxy_post(backend: str, path: str, data: dict) -> tuple[dict, int]:
    """POST to a backend service and return (json, status_code)."""
    try:
        # Forward original client info so audit logging captures the real client
        fwd_headers = {
            "X-Forwarded-For": request.headers.get("X-Forwarded-For", request.remote_addr),
            "X-Forwarded-User-Agent": request.headers.get("User-Agent", ""),
        }
        r = requests.post(
            f"{backend}{path}",
            json=data,
            headers=fwd_headers,
            timeout=BACKEND_TIMEOUT,
        )
        return r.json(), r.status_code
    except Exception as exc:
        log.exception("Backend POST %s%s failed", backend, path)
        return {"error": str(exc)}, 502


# -------------------------------------------------------------------------
# HTML template
# -------------------------------------------------------------------------

PAGE_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UniFi Admin Portal</title>
<link rel="stylesheet" href="/static/suite.css">
</head>
<body>

<div class="header">
  <h1><span>UniFi</span> Admin Suite</h1>
  <div class="header-meta">Physical Security Management</div>
</div>

<nav class="tabs" role="tablist" aria-label="Apps">
  <button class="tab active" data-panel="cameras" role="tab" aria-controls="panel-cameras" aria-selected="true">
    Cameras
    {% if cam_off_count %}
      <span class="count alert">{{ cam_off_count }} privacy</span>
    {% else %}
      <span class="count">{{ cameras | length }}</span>
    {% endif %}
  </button>
  <button class="tab" data-panel="doors" role="tab" aria-controls="panel-doors" aria-selected="false">
    Doors
    {% if door_unlocked_count %}
      <span class="count alert">{{ door_unlocked_count }} unlocked</span>
    {% else %}
      <span class="count">{{ doors | length }}</span>
    {% endif %}
  </button>
  <button class="tab" data-panel="monitor" role="tab" aria-controls="panel-monitor" aria-selected="false">
    Monitor
    {% if mon_offline_count %}
      <span class="count alert">{{ mon_offline_count }} offline</span>
    {% else %}
      <span class="count">{{ monitors | length }}</span>
    {% endif %}
  </button>
  <button class="tab" data-panel="audit" role="tab" aria-controls="panel-audit" aria-selected="false">
    Audit
    <span class="count">{{ audit_today_count }}</span>
  </button>
</nav>

<main class="content">

<div class="panel active" id="panel-cameras"><section class="control-list" data-kind="camera" data-base="/api/cameras">
<div class="freshness" role="status">Checking for updates…</div>
<div class="error-box service-error" {% if not cam_error %}hidden{% endif %}>Camera service unavailable. Check the connection and retry.</div>
<div class="section-bar"><span class="section-summary"></span><div><button data-bulk="enable-all">Enable all cameras</button> <button data-refresh>Refresh</button></div></div>
<div class="list-tools"><label>Search cameras<input type="search" data-search placeholder="Device name or location"></label><label>Show<select data-filter><option value="all">All cameras</option><option value="attention">Privacy active</option><option value="offline">Offline</option><option value="timers">Active timers</option></select></label></div>
<div class="item-list">
{% for cam in cameras %}
<article class="item-card {{ 'off' if cam.isOff else 'on' }}" data-device="{{ cam.id }}" data-name="{{ cam.name }}" data-active="{{ 'false' if cam.isOff else 'true' }}" data-offline="{{ 'true' if cam.state != 'CONNECTED' else 'false' }}">
<div class="item-top"><div class="item-info"><h2 class="item-name">{{ cam.name }}</h2><div class="state-line"><span class="badge {{ 'privacy' if cam.isOff else 'connected' }}">{{ 'Privacy active' if cam.isOff else 'Recording enabled' }}</span>{% if cam.state != "CONNECTED" %}<span class="badge disconnected">Offline</span>{% else %}<span class="badge connected">Connected</span>{% endif %}</div></div>
<div class="device-actions"><button class="primary" data-disclose aria-expanded="false">Privacy for…</button><button data-toggle>{{ 'Enable recording' if cam.isOff else 'Pause recording' }}</button></div></div>
<details class="device-details-toggle"><summary>Device details</summary><div class="item-meta">Model: {{ cam.type }} · Recording mode: {{ cam.recordingMode }}{% if cam.host %} · IP: {{ cam.host }}{% endif %}</div></details>
<div class="timed-options" hidden><form><label>Duration<select class="time-select" data-duration><option value="5">5 minutes</option><option value="15" selected>15 minutes</option><option value="30">30 minutes</option><option value="60">1 hour</option><option value="120">2 hours</option><option value="custom">Custom</option></select></label><label data-custom-label hidden>Minutes (1–480)<input class="time-select" data-custom type="number" min="1" max="480" step="1" value="15"></label><label class="reason">Reason (optional)<input class="time-select" data-reason maxlength="500" placeholder="Add context for the audit log"></label><button class="primary" type="submit">Start privacy</button></form><p class="time-preview"></p></div>
<div class="timer-display" hidden><span data-countdown></span><button data-cancel>Enable recording now</button></div><div class="card-feedback" role="status"></div>
</article>{% endfor %}</div><div class="empty-state" hidden>No matching cameras. <button data-clear>Clear filters</button></div></section></div>
<div class="panel " id="panel-doors"><section class="control-list" data-kind="door" data-base="/api/doors">
<div class="freshness" role="status">Checking for updates…</div>
<div class="error-box service-error" {% if not door_error %}hidden{% endif %}>Door service unavailable. Check the connection and retry.</div>
<div class="section-bar"><span class="section-summary"></span><div><button data-bulk="lock-all">Lock all doors</button> <button data-refresh>Refresh</button></div></div>
<div class="list-tools"><label>Search doors<input type="search" data-search placeholder="Device name or location"></label><label>Show<select data-filter><option value="all">All doors</option><option value="attention">Unlocked</option><option value="timers">Active timers</option></select></label></div>
<div class="item-list">
{% for door in doors %}
<article class="item-card {{ 'unlocked' if door.isUnlocked else 'locked' }}" data-device="{{ door.id }}" data-name="{{ door.name }}" data-active="{{ 'false' if door.isUnlocked else 'true' }}" data-offline="false">
<div class="item-top"><div class="item-info"><h2 class="item-name">{{ door.name }}</h2><div class="state-line"><span class="badge {{ 'unlocked' if door.isUnlocked else 'locked' }}">{{ 'Unlocked' if door.isUnlocked else 'Locked' }}</span></div></div>
<div class="device-actions"><button class="primary" data-disclose aria-expanded="false">Unlock for…</button><button data-toggle>{{ 'Lock now' if door.isUnlocked else 'Unlock' }}</button></div></div>
<details class="device-details-toggle"><summary>Device details</summary><div class="item-meta">Model: {{ door.type or "Unknown" }} · Controller rule: {{ door.lockRule }}</div></details>
<div class="timed-options" hidden><form><label>Duration<select class="time-select" data-duration><option value="5">5 minutes</option><option value="15" selected>15 minutes</option><option value="30">30 minutes</option><option value="60">1 hour</option><option value="120">2 hours</option><option value="custom">Custom</option></select></label><label data-custom-label hidden>Minutes (1–480)<input class="time-select" data-custom type="number" min="1" max="480" step="1" value="15"></label><label class="reason">Reason (optional)<input class="time-select" data-reason maxlength="500" placeholder="Add context for the audit log"></label><button class="primary" type="submit">Unlock temporarily</button></form><p class="time-preview"></p></div>
<div class="timer-display" hidden><span data-countdown></span><button data-cancel>Lock now</button></div><div class="card-feedback" role="status"></div>
</article>{% endfor %}</div><div class="empty-state" hidden>No matching doors. <button data-clear>Clear filters</button></div></section></div>
  <!-- ════ MONITOR PANEL ════ -->
  <div class="panel" id="panel-monitor"><div class="freshness" role="status"></div>
    {% if mon_error %}
      <div class="error-box">Monitor service unavailable: {{ mon_error }}</div>
    {% elif monitors | length == 0 %}
      <div class="empty-state">No devices found.</div>
    {% else %}
      <div class="section-bar">
        <span class="section-summary">
          {{ monitors | length }} device{{ 's' if monitors | length != 1 }}
          &middot; {{ mon_offline_count }} offline
        </span>
        <div>
          <a class="btn" href="http://{{ request.host.split(':')[0] }}:5002" target="_blank" rel="noopener">Full dashboard ↗</a>
          <button class="btn" data-refresh>Refresh</button>
        </div>
      </div>
      <div class="item-list">
      {% for dev in monitors %}
        <div class="item-card {{ 'disconnected' if not dev.online else 'on' }}">
          <div class="item-top">
          <div class="item-info">
            <div class="item-name">{{ dev.name }}</div>
            <details class="device-details-toggle"><summary>Device details</summary><div class="item-meta">
              {{ dev.type }}
              {% if dev.ip %}&middot; {{ dev.ip }}{% endif %}
              {% if dev.firmware %}&middot; FW: {{ dev.firmware }}{% endif %}
              {% if dev.uptime %}&middot; Up: {{ dev.uptime }}{% endif %}
            </div></details>
          </div>
          <div class="toggle-wrap">
            <span class="badge {{ 'connected' if dev.online else 'disconnected' }}">{{ 'ONLINE' if dev.online else 'OFFLINE' }}</span>
          </div>
          </div>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  </div>

  <!-- ════ AUDIT PANEL ════ -->
  <div class="panel" id="panel-audit"><div class="freshness" role="status"></div>
    {% if audit_error %}
      <div class="error-box">Audit service unavailable: {{ audit_error }}</div>
    {% else %}
      <div class="section-bar">
        <span class="section-summary">
          {{ audit_today_count }} entries today
          &middot; {{ audit_total }} total (last 7 days)
        </span>
        <div>
          <a class="btn" href="http://{{ request.host.split(':')[0] }}:5004" target="_blank" rel="noopener">Full audit log ↗</a>
          <button class="btn" data-refresh>Refresh</button>
        </div>
      </div>
      <div class="item-list">
      {% for e in audit_recent %}
        <div class="item-card {{ 'off' if 'off' in e.action else 'unlocked' if 'unlock' in e.action else 'on' }}">
          <div class="item-top">
          <div class="item-info">
            <div class="item-name">{{ e.icon }} {{ e.action_label }} — {{ e.target }}</div>
            <div class="item-meta">
              {{ e.timestamp }}
              &middot; <span class="badge {{ 'privacy' if e.category == 'camera' else 'unlocked' }}">{{ e.category | upper }}</span>
              &middot; {{ e.client_host }}
              {% if e.duration_min %}&middot; {{ e.duration_min }} min{% endif %}
            </div>
          </div>
          </div>
          {% if e.reason %}
          <div style="margin-top:.35rem;font-size:14px;color:var(--text);font-style:italic;padding:.25rem .5rem;background:rgba(59,130,246,.05);border-left:2px solid var(--accent);border-radius:0 4px 4px 0">{{ e.reason }}</div>
          {% endif %}
        </div>
      {% endfor %}
      {% if audit_recent | length == 0 %}
        <div class="empty-state">No recent audit entries.</div>
      {% endif %}
      </div>
    {% endif %}
  </div>

</main>

<div class="toast" id="toast" role="status"></div>

<script src="/static/controls.js"></script>
</body>
</html>
"""

# -------------------------------------------------------------------------
# Routes — main page
# -------------------------------------------------------------------------

@app.route("/")
def index():
    cameras = []
    cam_error = None
    doors = []
    door_error = None

    cam_data = _fetch_camera_list()
    if cam_data is None:
        cam_error = "Cannot reach camera service on port 5000"
    else:
        cameras = cam_data

    door_data = _fetch_door_list()
    if door_data is None:
        door_error = "Cannot reach door service on port 5001"
    else:
        doors = door_data

    cam_off_count = sum(1 for c in cameras if c.get("isOff"))
    door_unlocked_count = sum(1 for d in doors if d.get("isUnlocked"))

    monitors = []
    mon_error = None
    mon_data = _fetch_monitor_list()
    if mon_data is None:
        mon_error = "Cannot reach monitor service on port 5002"
    else:
        monitors = mon_data
    mon_offline_count = sum(1 for m in monitors if not m.get("online", True))

    audit_recent = []
    audit_today_count = 0
    audit_total = 0
    audit_error = None
    audit_data = _fetch_audit_summary()
    if audit_data is None:
        audit_error = "Cannot reach audit service on port 5004"
    else:
        audit_recent = audit_data.get("recent", [])
        audit_today_count = audit_data.get("today_count", 0)
        audit_total = audit_data.get("total_entries", 0)

    return render_template_string(
        PAGE_TEMPLATE,
        cameras=cameras,
        cam_error=cam_error,
        cam_off_count=cam_off_count,
        doors=doors,
        door_error=door_error,
        door_unlocked_count=door_unlocked_count,
        monitors=monitors,
        mon_error=mon_error,
        mon_offline_count=mon_offline_count,
        audit_recent=audit_recent,
        audit_today_count=audit_today_count,
        audit_total=audit_total,
        audit_error=audit_error,
    )


def _fetch_camera_list():
    """Get camera list from the camera backend."""
    try:
        r = requests.get(
            f"{config.CAMERA_BACKEND}/api/list",
            timeout=BACKEND_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json().get("cameras", [])
    except Exception:
        pass
    return None


def _fetch_door_list():
    """Get door list from the door backend."""
    try:
        r = requests.get(
            f"{config.DOOR_BACKEND}/api/list",
            timeout=BACKEND_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json().get("doors", [])
    except Exception:
        pass
    return None


def _fetch_monitor_list():
    """Get device list from the monitor backend and normalize fields."""
    try:
        r = requests.get(
            f"{config.MONITOR_BACKEND}/api/list",
            timeout=BACKEND_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            devices = data.get("devices", data.get("monitors", []))
            # Normalize the 'online' field — the monitor backend may use
            # different field names depending on the collector
            for dev in devices:
                if "online" not in dev:
                    # Check common alternatives
                    if "status" in dev:
                        dev["online"] = dev["status"] in ("online", "CONNECTED", "connected", True)
                    elif "isOnline" in dev:
                        dev["online"] = bool(dev["isOnline"])
                    elif "state" in dev:
                        dev["online"] = dev["state"] in ("CONNECTED", "online", "up")
                    else:
                        # If we got data at all, assume online
                        dev["online"] = True
            return devices
    except Exception:
        pass
    return None


def _fetch_audit_summary():
    """Get audit log summary from the audit backend."""
    try:
        r = requests.get(
            f"{config.AUDIT_BACKEND}/api/list",
            timeout=BACKEND_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# -------------------------------------------------------------------------
# Routes — API proxies
# -------------------------------------------------------------------------

@app.route("/api/cameras/toggle", methods=["POST"])
def proxy_camera_toggle():
    data = request.get_json(force=True)
    result, status = _proxy_post(config.CAMERA_BACKEND, "/api/toggle", data)
    return jsonify(result), status


@app.route("/api/cameras/enable-all", methods=["POST"])
def proxy_camera_enable_all():
    result, status = _proxy_post(config.CAMERA_BACKEND, "/api/enable-all", {})
    return jsonify(result), status


@app.route("/api/cameras/timed-off", methods=["POST"])
def proxy_camera_timed_off():
    data = request.get_json(force=True)
    result, status = _proxy_post(config.CAMERA_BACKEND, "/api/timed-off", data)
    return jsonify(result), status


@app.route("/api/cameras/cancel-timer", methods=["POST"])
def proxy_camera_cancel_timer():
    data = request.get_json(force=True)
    result, status = _proxy_post(config.CAMERA_BACKEND, "/api/cancel-timer", data)
    return jsonify(result), status


@app.route("/api/cameras/timers")
def proxy_camera_timers():
    data = _proxy_get(config.CAMERA_BACKEND, "/api/timers")
    return jsonify(data or {})


@app.route("/api/doors/toggle", methods=["POST"])
def proxy_door_toggle():
    data = request.get_json(force=True)
    result, status = _proxy_post(config.DOOR_BACKEND, "/api/toggle", data)
    return jsonify(result), status


@app.route("/api/doors/lock-all", methods=["POST"])
def proxy_door_lock_all():
    result, status = _proxy_post(config.DOOR_BACKEND, "/api/lock-all", {})
    return jsonify(result), status


@app.route("/api/doors/timed-unlock", methods=["POST"])
def proxy_door_timed_unlock():
    data = request.get_json(force=True)
    result, status = _proxy_post(config.DOOR_BACKEND, "/api/timed-unlock", data)
    return jsonify(result), status


@app.route("/api/doors/cancel-timer", methods=["POST"])
def proxy_door_cancel_timer():
    data = request.get_json(force=True)
    result, status = _proxy_post(config.DOOR_BACKEND, "/api/cancel-timer", data)
    return jsonify(result), status


@app.route("/api/doors/timers")
def proxy_door_timers():
    data = _proxy_get(config.DOOR_BACKEND, "/api/timers")
    return jsonify(data or {})


# -------------------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
