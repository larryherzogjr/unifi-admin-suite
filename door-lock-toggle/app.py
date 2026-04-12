"""
Flask web UI for toggling UniFi Access door locks.

Run:  python app.py
Then visit http://your-server:5001
"""

import logging
from flask import Flask, render_template_string, request, jsonify

import config
import access_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("app")

app = Flask(__name__)

# -------------------------------------------------------------------------
# HTML template — single-page admin panel
# -------------------------------------------------------------------------

PAGE_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Door Lock Toggle</title>
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

  h1 span {
    color: var(--accent);
   }

  .subtitle {
    color: var(--muted);
    font-size: .85rem;
    margin-bottom: 1.5rem;
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
  .btn.danger { border-color: var(--danger); color: var(--danger); }
  .btn.danger:hover { background: rgba(239,68,68,.12); }
  .btn.success { border-color: var(--success); color: var(--success); }
  .btn.success:hover { background: rgba(34,197,94,.12); }

  .door-list { display: flex; flex-direction: column; gap: .5rem; }

  .door-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: .9rem 1.1rem;
    transition: border-color .2s;
  }
  .door-card.unlocked { border-left: 3px solid var(--warn); }
  .door-card.locked   { border-left: 3px solid var(--success); }

  .door-info { flex: 1; min-width: 0; }
  .door-name {
    font-weight: 600;
    font-size: .95rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .door-meta {
    font-size: .75rem;
    color: var(--muted);
    margin-top: .15rem;
  }

  .toggle-wrap { flex-shrink: 0; margin-left: 1rem; display: flex; align-items: center; gap: .5rem; }
  .toggle-label { font-size: .75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; min-width: 60px; text-align: right; }

  .switch {
    position: relative;
    width: 44px;
    height: 24px;
  }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider {
    position: absolute; inset: 0;
    background: var(--warn);
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
  .badge.locked   { background: rgba(34,197,94,.15);  color: var(--success); }
  .badge.unlocked { background: rgba(245,158,11,.15); color: var(--warn); }

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
  .toast.warn { background: var(--warn); color: #000; }

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
  <h1><span>Grace Free</span> Door Lock Toggle</h1>
  <p class="subtitle">{{ host }}:{{ port }} &mdash; Unlock doors temporarily, lock when done.</p>

  {% if error %}
    <div class="error-box">{{ error }}</div>
  {% else %}
    <div class="topbar">
      <span style="font-size:.8rem;color:var(--muted)">
        {{ doors | length }} door{{ 's' if doors | length != 1 }}
        &nbsp;&middot;&nbsp;
        {{ doors | selectattr('isUnlocked') | list | length }} unlocked
      </span>
      <div>
        <button class="btn" onclick="location.reload()">Refresh</button>
      </div>
    </div>

    <div class="door-list">
    {% for door in doors %}
      <div class="door-card {{ 'unlocked' if door.isUnlocked else 'locked' }}" id="card-{{ door.id }}">
        <div class="door-info">
          <div class="door-name">{{ door.name }}</div>
          <div class="door-meta">
            {% if door.type %}{{ door.type }} &nbsp;&middot;&nbsp;{% endif %}
            <span class="badge {{ 'unlocked' if door.isUnlocked else 'locked' }}">
              {{ 'UNLOCKED' if door.isUnlocked else 'LOCKED' }}
            </span>
            &nbsp;&middot;&nbsp;
            Rule: <strong>{{ door.lockRule }}</strong>
          </div>
        </div>
        <div class="toggle-wrap">
          <span class="toggle-label" id="label-{{ door.id }}">{{ 'unlocked' if door.isUnlocked else 'locked' }}</span>
          <label class="switch">
            <input type="checkbox"
                   id="toggle-{{ door.id }}"
                   data-id="{{ door.id }}"
                   data-name="{{ door.name }}"
                   {{ '' if door.isUnlocked else 'checked' }}
                   onchange="toggleDoor(this)">
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

async function toggleDoor(el) {
  const id = el.dataset.id;
  const name = el.dataset.name;
  const shouldLock = el.checked;
  const label = document.getElementById('label-' + id);
  const card  = document.getElementById('card-' + id);

  el.disabled = true;
  label.textContent = '...';

  try {
    const r = await fetch('/api/toggle', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ door_id: id, lock: shouldLock }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'API error');

    const isUnlocked = !shouldLock;
    label.textContent = isUnlocked ? 'unlocked' : 'locked';
    card.className = 'door-card ' + (isUnlocked ? 'unlocked' : 'locked');
    toast(name + ' → ' + (isUnlocked ? 'UNLOCKED' : 'LOCKED'), 'ok');
  } catch (err) {
    el.checked = !shouldLock;
    label.textContent = shouldLock ? 'unlocked' : 'locked';
    toast('Error: ' + err.message, 'err');
  } finally {
    el.disabled = false;
  }
}

async function lockAll() {
  if (!confirm('Lock ALL doors?')) return;
  try {
    const r = await fetch('/api/lock-all', { method: 'POST' });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'API error');
    toast('Locked ' + data.changed + ' door(s)', 'ok');
    setTimeout(() => location.reload(), 800);
  } catch (err) {
    toast('Error: ' + err.message, 'err');
  }
}
</script>
</body>
</html>
"""

# -------------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------------

@app.route("/")
def index():
    try:
        doors = [access_api.door_summary(d) for d in access_api.list_doors()]
        return render_template_string(
            PAGE_TEMPLATE,
            doors=doors,
            error=None,
            host=config.ACCESS_HOST,
            port=config.ACCESS_PORT,
        )
    except Exception as exc:
        log.exception("Failed to load doors")
        return render_template_string(
            PAGE_TEMPLATE,
            doors=[],
            error=str(exc),
            host=config.ACCESS_HOST,
            port=config.ACCESS_PORT,
        )


@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    data = request.get_json(force=True)
    door_id = data.get("door_id")
    should_lock = data.get("lock", True)

    if not door_id:
        return jsonify({"error": "door_id required"}), 400

    try:
        if should_lock:
            access_api.lock_door(door_id)
        else:
            access_api.unlock_door(door_id)

        return jsonify({"ok": True, "locked": should_lock})
    except Exception as exc:
        log.exception("Toggle failed for %s", door_id)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/lock-all", methods=["POST"])
def api_lock_all():
    try:
        changed = access_api.ensure_all_doors_locked()
        return jsonify({"ok": True, "changed": len(changed), "doors": changed})
    except Exception as exc:
        log.exception("Lock-all failed")
        return jsonify({"error": str(exc)}), 500


# -------------------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------------------

@app.route("/api/list")
def api_list():
    try:
        doors = [access_api.door_summary(d) for d in access_api.list_doors()]
        return jsonify({"doors": doors})
    except Exception as exc:
        return jsonify({"error": str(exc), "doors": []}), 500

if __name__ == "__main__":
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
