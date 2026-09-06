"""
Flask web UI for toggling UniFi Protect cameras on/off.

Features:
  - Toggle individual cameras on/off for privacy
  - Advanced mode: timed privacy with automatic re-enable
  - Group-based camera filtering via URL paths
  - Portal integration via /api/list

Groups are defined in config.py under CAMERA_GROUPS.

Run:  python app.py
Then visit http://your-server:5000
"""

import logging
import threading
from datetime import datetime, timedelta

from flask import Flask, render_template_string, request, jsonify

import config
import protect_api
import audit_helper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("app")
app = Flask(__name__)

audit_helper.init(
    "/var/log/unifi-camera-audit.log",
    unifi_network=getattr(config, "UNIFI_NETWORK", None),
)

# In-memory map of camera_id → original recording mode
_original_modes: dict[str, str] = {}

# ── Timed privacy tracking ──
timed_privacies = {}  # { cam_id: { name, off_at, on_at, duration_min, timer, original_mode } }
timed_lock = threading.Lock()

def _auto_enable(cam_id, cam_name, original_mode):
    log.info("Timer expired for %s (%s) — auto-enabling", cam_name, cam_id)
    try:
        protect_api.set_camera_on(cam_id, original_mode)
        _original_modes.pop(cam_id, None)
        log.info("Auto-enabled %s successfully (restored mode: %s)", cam_name, original_mode)
    except Exception:
        log.exception("Auto-enable FAILED for %s — safety net will catch it", cam_name)
    finally:
        with timed_lock:
            timed_privacies.pop(cam_id, None)

def start_timed_privacy(cam_id, cam_name, minutes, original_mode):
    cancel_timer(cam_id)
    # Remember original mode
    if original_mode and original_mode != "never":
        _original_modes[cam_id] = original_mode
    mode_to_restore = _original_modes.get(cam_id, "always")
    # Turn camera off
    protect_api.set_camera_off(cam_id)
    # Schedule auto-enable
    timer = threading.Timer(minutes * 60, _auto_enable, args=[cam_id, cam_name, mode_to_restore])
    timer.daemon = True
    timer.start()
    with timed_lock:
        timed_privacies[cam_id] = {
            "name": cam_name,
            "off_at": datetime.now(),
            "on_at": datetime.now() + timedelta(minutes=minutes),
            "duration_min": minutes,
            "timer": timer,
            "original_mode": mode_to_restore,
        }
    log.info("Timed privacy: %s for %d min (auto-enable at %s)",
             cam_name, minutes, (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M:%S"))

def cancel_timer(cam_id):
    with timed_lock:
        entry = timed_privacies.pop(cam_id, None)
    if entry and entry["timer"]:
        entry["timer"].cancel()
        log.info("Cancelled timer for %s", entry["name"])

def get_active_timers():
    now = datetime.now()
    result = {}
    with timed_lock:
        for cid, e in timed_privacies.items():
            rem = (e["on_at"] - now).total_seconds()
            if rem > 0:
                result[cid] = {"name": e["name"], "remaining_sec": int(rem),
                               "duration_min": e["duration_min"], "on_at": e["on_at"].strftime("%H:%M:%S")}
    return result

# ── HTML Template ──
PAGE_TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cameras · UniFi Admin Suite</title><link rel="stylesheet" href="/static/suite.css"></head><body><header class="suite-header"><div><a class="suite-brand" data-portal-link href="/">UniFi Admin Suite</a><h1>Cameras</h1><p>Manage recording and temporary privacy.</p></div><a class="btn" data-portal-link href="/">Admin portal</a></header><main class="content">{% if group_name != "default" %}<p>Group: {{ group_name }}</p>{% endif %}<section class="control-list" data-kind="camera" data-base="/api">
<div class="freshness" role="status">Checking for updates…</div>
<div class="error-box service-error" {% if not error %}hidden{% endif %}>Camera service unavailable. Check the connection and retry.</div>
<div class="section-bar"><span class="section-summary"></span><div> <button data-refresh>Refresh</button></div></div>
<div class="list-tools"><label>Search cameras<input type="search" data-search placeholder="Device name or location"></label><label>Show<select data-filter><option value="all">All cameras</option><option value="attention">Privacy active</option><option value="offline">Offline</option><option value="timers">Active timers</option></select></label></div>
<div class="item-list">
{% for cam in cameras %}
<article class="item-card {{ 'off' if cam.isOff else 'on' }}" data-device="{{ cam.id }}" data-name="{{ cam.name }}" data-active="{{ 'false' if cam.isOff else 'true' }}" data-offline="{{ 'true' if cam.state != 'CONNECTED' else 'false' }}">
<div class="item-top"><div class="item-info"><h2 class="item-name">{{ cam.name }}</h2><div class="state-line"><span class="badge {{ 'privacy' if cam.isOff else 'connected' }}">{{ 'Privacy active' if cam.isOff else 'Recording enabled' }}</span>{% if cam.state != "CONNECTED" %}<span class="badge disconnected">Offline</span>{% else %}<span class="badge connected">Connected</span>{% endif %}</div></div>
<div class="device-actions"><button class="primary" data-disclose aria-expanded="false">Privacy for…</button><button data-toggle>{{ 'Enable recording' if cam.isOff else 'Pause recording' }}</button></div></div>
<details class="device-details-toggle"><summary>Device details</summary><div class="item-meta">Model: {{ cam.type }} · Recording mode: {{ cam.recordingMode }}{% if cam.host %} · IP: {{ cam.host }}{% endif %}</div></details>
<div class="timed-options" hidden><form><label>Duration<select class="time-select" data-duration><option value="5">5 minutes</option><option value="15" selected>15 minutes</option><option value="30">30 minutes</option><option value="60">1 hour</option><option value="120">2 hours</option><option value="custom">Custom</option></select></label><label data-custom-label hidden>Minutes (1–480)<input class="time-select" data-custom type="number" min="1" max="480" step="1" value="15"></label><label class="reason">Reason (optional)<input class="time-select" data-reason maxlength="500" placeholder="Add context for the audit log"></label><button class="primary" type="submit">Start privacy</button></form><p class="time-preview"></p></div>
<div class="timer-display" hidden><span data-countdown></span><button data-cancel>Enable recording now</button></div><div class="card-feedback" role="status"></div>
</article>{% endfor %}</div><div class="empty-state" hidden>No matching cameras. <button data-clear>Clear filters</button></div></section></main><div id="toast" class="toast" role="status"></div><script src="/static/controls.js"></script></body></html>"""

# ── Routes ──
def _render_group(group_name):
    groups = getattr(config, "CAMERA_GROUPS", {})
    if group_name != "default" and group_name not in groups:
        return render_template_string(PAGE_TEMPLATE, cameras=[], error=f'Unknown group: "{group_name}". Available: {", ".join(groups.keys())}',
                                      host=config.PROTECT_HOST, group_name=group_name), 404
    try:
        cameras = [protect_api.camera_summary(c) for c in protect_api.list_cameras(group=group_name)]
        for cam in cameras:
            if not cam["isOff"] and cam["id"] not in _original_modes:
                _original_modes[cam["id"]] = cam["recordingMode"]
        return render_template_string(PAGE_TEMPLATE, cameras=cameras, error=None, host=config.PROTECT_HOST, group_name=group_name)
    except Exception as exc:
        log.exception("Failed to load cameras for group '%s'", group_name)
        return render_template_string(PAGE_TEMPLATE, cameras=[], error=str(exc), host=config.PROTECT_HOST, group_name=group_name)

@app.route("/")
def index():
    return _render_group("default")

@app.route("/<group_name>")
def group_index(group_name):
    if group_name.startswith("api"):
        return jsonify({"error": "not found"}), 404
    return _render_group(group_name)

@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    data = request.get_json(force=True)
    camera_id = data.get("camera_id")
    enable = data.get("enable", True)
    reason = data.get("reason", "")
    if not camera_id: return jsonify({"error": "camera_id required"}), 400
    try:
        if enable:
            cancel_timer(camera_id)
            mode = _original_modes.pop(camera_id, None)
            result = protect_api.set_camera_on(camera_id, mode)
            audit_helper.write("camera_on", result.get("name", camera_id), reason)
        else:
            current = protect_api.get_camera(camera_id)
            cam_name = current.get("name", camera_id)
            cur_mode = current.get("recordingSettings", {}).get("mode", "always")
            if cur_mode != "never":
                _original_modes[camera_id] = cur_mode
            result = protect_api.set_camera_off(camera_id)
            audit_helper.write("camera_off", cam_name, reason)
        return jsonify({"ok": True, "camera": protect_api.camera_summary(result)})
    except Exception as exc:
        log.exception("Toggle failed for %s", camera_id)
        return jsonify({"error": str(exc)}), 500

@app.route("/api/timed-off", methods=["POST"])
def api_timed_off():
    data = request.get_json(force=True)
    camera_id = data.get("camera_id")
    minutes = data.get("minutes")
    if not camera_id: return jsonify({"error": "camera_id required"}), 400
    if not minutes or not isinstance(minutes, (int, float)) or minutes < 1:
        return jsonify({"error": "minutes must be a positive number"}), 400
    if minutes > 480: return jsonify({"error": "max 8 hours (480 min)"}), 400
    minutes = int(minutes)
    try:
        current = protect_api.get_camera(camera_id)
        cam_name = current.get("name", "Unknown")
        cur_mode = current.get("recordingSettings", {}).get("mode", "always")
        start_timed_privacy(camera_id, cam_name, minutes, cur_mode)
        audit_helper.write("timed_camera_off", cam_name, data.get("reason", ""), duration_min=minutes)
        return jsonify({"ok": True, "camera_id": camera_id, "name": cam_name, "minutes": minutes,
                        "on_at": (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M:%S")})
    except Exception as exc:
        log.exception("Timed off failed for %s", camera_id)
        return jsonify({"error": str(exc)}), 500

@app.route("/api/cancel-timer", methods=["POST"])
def api_cancel_timer():
    data = request.get_json(force=True)
    camera_id = data.get("camera_id")
    if not camera_id: return jsonify({"error": "camera_id required"}), 400
    try:
        entry = timed_privacies.get(camera_id, {})
        cam_name = entry.get("name", "Unknown")
        original_mode = entry.get("original_mode")
        cancel_timer(camera_id)
        protect_api.set_camera_on(camera_id, original_mode)
        _original_modes.pop(camera_id, None)
        audit_helper.write("cancel_timer_camera_on", cam_name, data.get("reason", "Timer cancelled"))
        return jsonify({"ok": True, "name": cam_name})
    except Exception as exc:
        log.exception("Cancel timer failed for %s", camera_id)
        return jsonify({"error": str(exc)}), 500

@app.route("/api/timers")
def api_timers():
    return jsonify(get_active_timers())

@app.route("/api/enable-all", methods=["POST"])
def api_enable_all():
    try:
        active_ids = list(timed_privacies.keys())
        for cid in active_ids:
            cancel_timer(cid)
        changed = protect_api.ensure_all_cameras_on()
        audit_helper.write("enable_all_cameras", f"{len(changed)} cameras", "")
        return jsonify({"ok": True, "changed": len(changed), "cameras": changed})
    except Exception as exc:
        log.exception("Enable-all failed")
        return jsonify({"error": str(exc)}), 500

@app.route("/api/list")
def api_list():
    try:
        cameras = [protect_api.camera_summary(c) for c in protect_api.list_all_cameras()]
        timers = get_active_timers()
        for cam in cameras:
            if not cam["isOff"] and cam["id"] not in _original_modes:
                _original_modes[cam["id"]] = cam["recordingMode"]
            if cam["id"] in timers:
                cam["timer"] = timers[cam["id"]]
        return jsonify({"cameras": cameras})
    except Exception as exc:
        return jsonify({"error": str(exc), "cameras": []}), 500

if __name__ == "__main__":
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
