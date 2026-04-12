"""
Flask web UI for toggling UniFi Protect cameras on/off.

Supports group-based camera filtering via URL paths:
  /         → shows the "default" group
  /bob      → shows cameras in the "bob" group
  /alice    → shows cameras in the "alice" group

Groups are defined in config.py under CAMERA_GROUPS.

Run:  python app.py
Then visit http://your-server:5000
"""

import logging
from flask import Flask, render_template_string, request, jsonify

import config
import protect_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("app")

app = Flask(__name__)

# In-memory map of camera_id → original recording mode, so we can restore
# the exact mode when turning a camera back on.
_original_modes: dict[str, str] = {}

# -------------------------------------------------------------------------
# HTML template — single-page admin panel
# -------------------------------------------------------------------------

PAGE_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Camera Privacy Toggle{% if group_name != 'default' %} — {{ group_name }}{% endif %}</title>
<style>
  :root {
    --bg:        #0f1114;
    --surface:   #1a1d23;
    --border:    #2a2d35;
    --text:      #e0e0e0;
    --muted:     #888;
    --accent:    #3b82f6;
    --danger:    #ef4444;
    --success:   #22c55e;
    --warn:      #f59e0b;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 2rem 1rem;
  }
  .container { max-width: 720px; margin: 0 auto; }

  h1 {
    font-size: 1.4rem;
    font-weight: 600;
    margin-bottom: .25rem;
  }
  .subtitle {
    color: var(--muted);
    font-size: .85rem;
    margin-bottom: 1.5rem;
  }
  .group-label {
    display: inline-block;
    background: var(--accent);
    color: #fff;
    font-size: .7rem;
    font-weight: 600;
    padding: .15rem .5rem;
    border-radius: 4px;
    margin-left: .5rem;
    text-transform: uppercase;
    letter-spacing: .03em;
    vertical-align: middle;
  }

  .topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .btn {
    display: inline-flex;
    align-items: center;
    gap: .4rem;
    padding: .5rem 1rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    font-size: .85rem;
    cursor: pointer;
    transition: background .15s;
  }
  .btn:hover { background: #252830; }

  .camera-list { display: flex; flex-direction: column; gap: .5rem; }

  .camera-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: .9rem 1.1rem;
    transition: border-color .2s;
  }
  .camera-card.off { border-left: 3px solid var(--danger); }
  .camera-card.on  { border-left: 3px solid var(--success); }

  .cam-info { flex: 1; min-width: 0; }
  .cam-name {
    font-weight: 600;
    font-size: .95rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .cam-meta {
    font-size: .75rem;
    color: var(--muted);
    margin-top: .15rem;
  }

  .toggle-wrap { flex-shrink: 0; margin-left: 1rem; display: flex; align-items: center; gap: .5rem; }
  .toggle-label { font-size: .75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }

  .switch {
    position: relative;
    width: 44px;
    height: 24px;
  }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider {
    position: absolute; inset: 0;
    background: var(--danger);
    border-radius: 24px;
    cursor: pointer;
    transition: background .25s;
  }
  .slider::before {
    content: "";
    position: absolute;
    left: 3px; bottom: 3px;
    width: 18px; height: 18px;
    background: #fff;
    border-radius: 50%;
    transition: transform .25s;
  }
  .switch input:checked + .slider { background: var(--success); }
  .switch input:checked + .slider::before { transform: translateX(20px); }
  .switch input:disabled + .slider { opacity: .4; cursor: not-allowed; }

  .badge {
    display: inline-block;
    font-size: .65rem;
    padding: .1rem .4rem;
    border-radius: 3px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .03em;
  }
  .badge.connected    { background: rgba(34,197,94,.15);  color: var(--success); }
  .badge.disconnected { background: rgba(239,68,68,.15);  color: var(--danger); }

  .toast {
    position: fixed;
    top: 1rem; right: 1rem;
    padding: .7rem 1.2rem;
    border-radius: 6px;
    font-size: .85rem;
    font-weight: 500;
    color: #fff;
    opacity: 0;
    transform: translateY(-10px);
    transition: opacity .3s, transform .3s;
    z-index: 99;
    pointer-events: none;
  }
  .toast.show { opacity: 1; transform: translateY(0); }
  .toast.ok   { background: var(--success); }
  .toast.err  { background: var(--danger); }

  .error-box {
    padding: 1.5rem;
    background: rgba(239,68,68,.08);
    border: 1px solid var(--danger);
    border-radius: 8px;
    color: var(--danger);
    font-size: .9rem;
  }
</style>
</head>
<body>
<div class="container">
  <h1>Camera Privacy Toggle
    {% if group_name != 'default' %}<span class="group-label">{{ group_name }}</span>{% endif %}
  </h1>
  <p class="subtitle">{{ host }} &mdash; Toggle cameras off for privacy, back on when done.</p>

  {% if error %}
    <div class="error-box">{{ error }}</div>
  {% else %}
    <div class="topbar">
      <span style="font-size:.8rem;color:var(--muted)">
        {{ cameras | length }} camera{{ 's' if cameras | length != 1 }}
        &nbsp;&middot;&nbsp;
        {{ cameras | selectattr('isOff') | list | length }} off
      </span>
      <div>
        <button class="btn" onclick="location.reload()">Refresh</button>
      </div>
    </div>

    <div class="camera-list">
    {% for cam in cameras %}
      <div class="camera-card {{ 'off' if cam.isOff else 'on' }}" id="card-{{ cam.id }}">
        <div class="cam-info">
          <div class="cam-name">{{ cam.name }}</div>
          <div class="cam-meta">
            {{ cam.type }}
            &nbsp;&middot;&nbsp;
            <span class="badge {{ 'connected' if cam.state == 'CONNECTED' else 'disconnected' }}">{{ cam.state }}</span>
            &nbsp;&middot;&nbsp;
            Mode: <strong>{{ cam.recordingMode }}</strong>
            {% if cam.host %}&nbsp;&middot;&nbsp;{{ cam.host }}{% endif %}
          </div>
        </div>
        <div class="toggle-wrap">
          <span class="toggle-label" id="label-{{ cam.id }}">{{ 'off' if cam.isOff else 'on' }}</span>
          <label class="switch">
            <input type="checkbox"
                   id="toggle-{{ cam.id }}"
                   data-id="{{ cam.id }}"
                   data-name="{{ cam.name }}"
                   {{ '' if cam.isOff else 'checked' }}
                   onchange="toggleCamera(this)">
            <span class="slider"></span>
          </label>
        </div>
      </div>
    {% endfor %}
    </div>
  {% endif %}
</div>

<div class="toast" id="toast"></div>

<script>
function toast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + (type || 'ok');
  setTimeout(() => el.classList.remove('show'), 3000);
}

async function toggleCamera(el) {
  const id = el.dataset.id;
  const name = el.dataset.name;
  const turnOn = el.checked;
  const label = document.getElementById('label-' + id);
  const card  = document.getElementById('card-' + id);

  el.disabled = true;
  label.textContent = '...';

  try {
    const r = await fetch('/api/toggle', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ camera_id: id, enable: turnOn }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'API error');

    label.textContent = data.camera.isOff ? 'off' : 'on';
    card.className = 'camera-card ' + (data.camera.isOff ? 'off' : 'on');
    const badge = card.querySelector('.badge');
    if (badge) {
      badge.textContent = data.camera.isOff ? 'OFF' : 'CONNECTED';
      badge.className = 'badge ' + (data.camera.isOff ? 'disconnected' : 'connected');
    }
    toast(name + ' → ' + (data.camera.isOff ? 'OFF (privacy)' : 'ON'), 'ok');
  } catch (err) {
    el.checked = !turnOn;
    label.textContent = turnOn ? 'off' : 'on';
    toast('Error: ' + err.message, 'err');
  } finally {
    el.disabled = false;
  }
}
</script>
</body>
</html>
"""

# -------------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------------

def _render_group(group_name: str):
    """Render the camera dashboard for a specific group."""
    groups = getattr(config, "CAMERA_GROUPS", {})
    if group_name != "default" and group_name not in groups:
        return render_template_string(
            PAGE_TEMPLATE,
            cameras=[],
            error=f"Unknown group: \"{group_name}\". Available groups: {', '.join(groups.keys())}",
            host=config.PROTECT_HOST,
            group_name=group_name,
        ), 404

    try:
        cameras = [protect_api.camera_summary(c) for c in protect_api.list_cameras(group=group_name)]
        # Seed our memory of original modes for cameras that are currently on
        for cam in cameras:
            if not cam["isOff"] and cam["id"] not in _original_modes:
                _original_modes[cam["id"]] = cam["recordingMode"]
        return render_template_string(
            PAGE_TEMPLATE,
            cameras=cameras,
            error=None,
            host=config.PROTECT_HOST,
            group_name=group_name,
        )
    except Exception as exc:
        log.exception("Failed to load cameras for group '%s'", group_name)
        return render_template_string(
            PAGE_TEMPLATE,
            cameras=[],
            error=str(exc),
            host=config.PROTECT_HOST,
            group_name=group_name,
        )


@app.route("/")
def index():
    return _render_group("default")


@app.route("/<group_name>")
def group_index(group_name):
    # Don't match API routes
    if group_name.startswith("api"):
        return jsonify({"error": "not found"}), 404
    return _render_group(group_name)


@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    data = request.get_json(force=True)
    camera_id = data.get("camera_id")
    enable = data.get("enable", True)

    if not camera_id:
        return jsonify({"error": "camera_id required"}), 400

    try:
        if enable:
            # Restore original mode if we know it
            mode = _original_modes.pop(camera_id, None)
            result = protect_api.set_camera_on(camera_id, mode)
        else:
            # Remember current mode before turning off
            current = protect_api.get_camera(camera_id)
            cur_mode = current.get("recordingSettings", {}).get("mode", "always")
            if cur_mode != "never":
                _original_modes[camera_id] = cur_mode
            result = protect_api.set_camera_off(camera_id)

        return jsonify({"ok": True, "camera": protect_api.camera_summary(result)})
    except Exception as exc:
        log.exception("Toggle failed for %s", camera_id)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/enable-all", methods=["POST"])
def api_enable_all():
    try:
        changed = protect_api.ensure_all_cameras_on()
        return jsonify({"ok": True, "changed": len(changed), "cameras": changed})
    except Exception as exc:
        log.exception("Enable-all failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/list")
def api_list():
    """For portal integration — returns ALL cameras (unfiltered)."""
    try:
        cameras = [protect_api.camera_summary(c) for c in protect_api.list_all_cameras()]
        for cam in cameras:
            if not cam["isOff"] and cam["id"] not in _original_modes:
                _original_modes[cam["id"]] = cam["recordingMode"]
        return jsonify({"cameras": cameras})
    except Exception as exc:
        return jsonify({"error": str(exc), "cameras": []}), 500


# -------------------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
