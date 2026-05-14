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
        r = requests.post(
            f"{backend}{path}",
            json=data,
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
<style>
  :root {
    --bg:        #0b0d10;
    --surface:   #14171c;
    --card:      #1a1d23;
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
  }

  /* ── Header ── */
  .header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 1.2rem 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: .5rem;
  }
  .header h1 {
    font-size: 1.2rem;
    font-weight: 700;
    letter-spacing: .02em;
  }
  .header h1 span { color: var(--accent); }
  .header-meta {
    font-size: .75rem;
    color: var(--muted);
  }

  /* ── Tabs ── */
  .tabs {
    display: flex;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 0 2rem;
  }
  .tab {
    padding: .8rem 1.5rem;
    font-size: .85rem;
    font-weight: 600;
    color: var(--muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: color .2s, border-color .2s;
    user-select: none;
  }
  .tab:hover { color: var(--text); }
  .tab.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
  }
  .tab .count {
    display: inline-block;
    font-size: .7rem;
    background: var(--border);
    color: var(--text);
    padding: .1rem .45rem;
    border-radius: 10px;
    margin-left: .4rem;
    font-weight: 500;
  }
  .tab .count.alert {
    background: rgba(239,68,68,.2);
    color: var(--danger);
  }

  /* ── Content ── */
  .content { padding: 1.5rem 2rem; max-width: 800px; margin: 0 auto; }
  .panel { display: none; }
  .panel.active { display: block; }

  .section-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
    flex-wrap: wrap;
    gap: .5rem;
  }
  .section-summary {
    font-size: .8rem;
    color: var(--muted);
  }

  .btn {
    display: inline-flex;
    align-items: center;
    gap: .4rem;
    padding: .45rem .9rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--card);
    color: var(--text);
    font-size: .8rem;
    cursor: pointer;
    transition: background .15s;
  }
  .btn:hover { background: #252830; }
  .btn.success { border-color: var(--success); color: var(--success); }
  .btn.success:hover { background: rgba(34,197,94,.1); }

  /* ── Item cards ── */
  .item-list { display: flex; flex-direction: column; gap: .5rem; }

  .item-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: .85rem 1rem;
    transition: border-color .2s;
  }
  .item-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .item-card.off      { border-left: 3px solid var(--danger); }
  .item-card.on       { border-left: 3px solid var(--success); }
  .item-card.unlocked { border-left: 3px solid var(--warn); }
  .item-card.locked   { border-left: 3px solid var(--success); }

  .item-info { flex: 1; min-width: 0; }
  .item-name {
    font-weight: 600;
    font-size: .9rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .item-meta {
    font-size: .72rem;
    color: var(--muted);
    margin-top: .15rem;
  }

  .toggle-wrap { flex-shrink: 0; margin-left: 1rem; display: flex; align-items: center; gap: .5rem; }
  .toggle-label {
    font-size: .7rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .04em;
    min-width: 55px;
    text-align: right;
  }

  .switch { position: relative; width: 40px; height: 22px; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider {
    position: absolute; inset: 0;
    border-radius: 22px;
    cursor: pointer;
    transition: background .25s;
  }
  .slider::before {
    content: "";
    position: absolute;
    left: 3px; bottom: 3px;
    width: 16px; height: 16px;
    background: #fff;
    border-radius: 50%;
    transition: transform .25s;
  }
  .switch input:checked + .slider::before { transform: translateX(18px); }
  .switch input:disabled + .slider { opacity: .4; cursor: not-allowed; }

  /* Camera: off=red slider, on=green */
  .cam-slider { background: var(--danger); }
  .switch input:checked + .cam-slider { background: var(--success); }

  /* Door: unlocked=amber slider, locked=green */
  .door-slider { background: var(--warn); }
  .switch input:checked + .door-slider { background: var(--success); }

  .badge {
    display: inline-block;
    font-size: .6rem;
    padding: .1rem .35rem;
    border-radius: 3px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .03em;
  }
  .badge.connected    { background: rgba(34,197,94,.15);  color: var(--success); }
  .badge.disconnected { background: rgba(239,68,68,.15);  color: var(--danger); }
  .badge.locked       { background: rgba(34,197,94,.15);  color: var(--success); }
  .badge.unlocked     { background: rgba(245,158,11,.15); color: var(--warn); }

  /* ── Advanced / Timed Unlock ── */
  .advanced-row{display:none;align-items:center;gap:.6rem;margin-top:.7rem;padding-top:.7rem;border-top:1px solid var(--border);flex-wrap:wrap}
  .advanced-row.show{display:flex}
  .adv-label{font-size:.72rem;color:var(--muted)}.adv-checkbox{cursor:pointer;accent-color:var(--accent)}
  .time-select{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:.25rem .4rem;font-size:.78rem}
  .time-select:focus{border-color:var(--accent);outline:none}
  .btn-timed{padding:.25rem .7rem;font-size:.75rem;border:1px solid var(--accent);border-radius:5px;background:rgba(59,130,246,.1);color:var(--accent);cursor:pointer;transition:background .15s}
  .btn-timed:hover{background:rgba(59,130,246,.2)}
  .timer-display{display:none;align-items:center;gap:.5rem;margin-top:.6rem;padding:.45rem .7rem;background:rgba(59,130,246,.06);border:1px solid rgba(59,130,246,.2);border-radius:6px}
  .timer-display.show{display:flex}.timer-icon{font-size:.9rem}.timer-text{font-size:.75rem;color:var(--accent)}
  .timer-countdown{font-size:.8rem;font-weight:600;color:var(--accent);font-variant-numeric:tabular-nums}
  .btn-cancel-timer{margin-left:auto;padding:.2rem .5rem;font-size:.7rem;border:1px solid var(--danger);border-radius:4px;background:transparent;color:var(--danger);cursor:pointer}
  .btn-cancel-timer:hover{background:rgba(239,68,68,.1)}

  /* ── Toast ── */
  .toast {
    position: fixed;
    top: 1rem; right: 1rem;
    padding: .65rem 1.1rem;
    border-radius: 6px;
    font-size: .82rem;
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
    padding: 1.2rem;
    background: rgba(239,68,68,.08);
    border: 1px solid var(--danger);
    border-radius: 8px;
    color: var(--danger);
    font-size: .85rem;
    margin-bottom: 1rem;
  }

  .empty-state {
    text-align: center;
    padding: 3rem;
    color: var(--muted);
    font-size: .9rem;
  }
</style>
</head>
<body>

<div class="header">
  <h1><span>UniFi</span> Admin Portal</h1>
  <div class="header-meta">Physical Security Management</div>
</div>

<div class="tabs">
  <div class="tab active" data-panel="cameras" onclick="switchTab(this)">
    Cameras
    {% if cam_off_count %}
      <span class="count alert">{{ cam_off_count }} off</span>
    {% else %}
      <span class="count">{{ cameras | length }}</span>
    {% endif %}
  </div>
  <div class="tab" data-panel="doors" onclick="switchTab(this)">
    Doors
    {% if door_unlocked_count %}
      <span class="count alert">{{ door_unlocked_count }} open</span>
    {% else %}
      <span class="count">{{ doors | length }}</span>
    {% endif %}
  </div>
  <div class="tab" data-panel="monitor" onclick="switchTab(this)">
    Monitor
    {% if mon_offline_count %}
      <span class="count alert">{{ mon_offline_count }} down</span>
    {% else %}
      <span class="count">{{ monitors | length }}</span>
    {% endif %}
  </div>
</div>

<div class="content">

  <!-- ════ CAMERAS PANEL ════ -->
  <div class="panel active" id="panel-cameras">
    {% if cam_error %}
      <div class="error-box">Camera service unavailable: {{ cam_error }}</div>
    {% elif cameras | length == 0 %}
      <div class="empty-state">No cameras found.</div>
    {% else %}
      <div class="section-bar">
        <span class="section-summary">
          {{ cameras | length }} camera{{ 's' if cameras | length != 1 }}
          &middot; {{ cam_off_count }} off
        </span>
        <div>
          <button class="btn success" onclick="enableAllCameras()">Enable All</button>
          <button class="btn" onclick="location.href=location.pathname+'?t='+Date.now()+(location.hash||'')">Refresh</button>
        </div>
      </div>
      <div class="item-list">
      {% for cam in cameras %}
        <div class="item-card {{ 'off' if cam.isOff else 'on' }}" id="cam-card-{{ cam.id }}">
          <div class="item-top">
          <div class="item-info">
            <div class="item-name">{{ cam.name }}</div>
            <div class="item-meta">
              {{ cam.type }}
              &middot;
              <span class="badge {{ 'connected' if cam.state == 'CONNECTED' else 'disconnected' }}">{{ cam.state }}</span>
              &middot; Mode: <strong>{{ cam.recordingMode }}</strong>
              {% if cam.host %}&middot; {{ cam.host }}{% endif %}
            </div>
          </div>
          <div class="toggle-wrap">
            <span class="toggle-label" id="cam-label-{{ cam.id }}">{{ 'off' if cam.isOff else 'on' }}</span>
            <label class="switch">
              <input type="checkbox"
                     id="cam-toggle-{{ cam.id }}"
                     data-id="{{ cam.id }}"
                     data-name="{{ cam.name }}"
                     {{ '' if cam.isOff else 'checked' }}
                     onchange="toggleCamera(this)">
              <span class="slider cam-slider"></span>
            </label>
          </div>
          </div>
          <div class="advanced-row {{ 'show' if not cam.isOff else '' }}" id="cam-adv-{{ cam.id }}">
            <label class="adv-label" style="display:flex;align-items:center;gap:.4rem;cursor:pointer"><input type="checkbox" class="adv-checkbox" id="cam-adv-check-{{ cam.id }}" onchange="toggleCamAdvanced('{{ cam.id }}')"> Advanced</label>
            <div id="cam-adv-options-{{ cam.id }}" style="display:none;align-items:center;gap:.5rem;flex-wrap:wrap">
              <label class="adv-label">Privacy for:</label>
              <select class="time-select" id="cam-time-{{ cam.id }}" onchange="camTimeChanged(this,'{{ cam.id }}')">
                <option value="5">5 min</option><option value="15" selected>15 min</option><option value="30">30 min</option><option value="60">1 hr</option><option value="120">2 hr</option><option value="custom">Custom...</option></select>
              <input type="number" id="cam-custom-time-{{ cam.id }}" min="1" max="480" placeholder="min" style="display:none;width:55px" class="time-select">
              <button class="btn-timed" onclick="timedOffCam('{{ cam.id }}','{{ cam.name }}')">&#9201; Timed Privacy</button>
            </div>
          </div>
          <div class="timer-display" id="cam-timer-{{ cam.id }}"><span class="timer-icon">&#9201;</span><span class="timer-text">Auto-enables in</span>
            <span class="timer-countdown" id="cam-countdown-{{ cam.id }}">--:--</span>
            <button class="btn-cancel-timer" onclick="cancelCamTimer('{{ cam.id }}')">Cancel &amp; Enable</button>
          </div>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  </div>

  <!-- ════ DOORS PANEL ════ -->
  <div class="panel" id="panel-doors">
    {% if door_error %}
      <div class="error-box">Door service unavailable: {{ door_error }}</div>
    {% elif doors | length == 0 %}
      <div class="empty-state">No doors found.</div>
    {% else %}
      <div class="section-bar">
        <span class="section-summary">
          {{ doors | length }} door{{ 's' if doors | length != 1 }}
          &middot; {{ door_unlocked_count }} unlocked
        </span>
        <div>
          <button class="btn success" onclick="lockAllDoors()">Lock All</button>
          <button class="btn" onclick="location.href=location.pathname+'?t='+Date.now()+(location.hash||'')">Refresh</button>
        </div>
      </div>
      <div class="item-list">
      {% for door in doors %}
        <div class="item-card {{ 'unlocked' if door.isUnlocked else 'locked' }}" id="door-card-{{ door.id }}">
          <div class="item-top">
          <div class="item-info">
            <div class="item-name">{{ door.name }}</div>
            <div class="item-meta">
              {% if door.type %}{{ door.type }} &middot;{% endif %}
              <span class="badge {{ 'unlocked' if door.isUnlocked else 'locked' }}" id="door-badge-{{ door.id }}">
                {{ 'UNLOCKED' if door.isUnlocked else 'LOCKED' }}
              </span>
              &middot; Rule: <strong>{{ door.lockRule }}</strong>
            </div>
          </div>
          <div class="toggle-wrap">
            <span class="toggle-label" id="door-label-{{ door.id }}">{{ 'unlocked' if door.isUnlocked else 'locked' }}</span>
            <label class="switch">
              <input type="checkbox"
                     id="door-toggle-{{ door.id }}"
                     data-id="{{ door.id }}"
                     data-name="{{ door.name }}"
                     {{ '' if door.isUnlocked else 'checked' }}
                     onchange="toggleDoor(this)">
              <span class="slider door-slider"></span>
            </label>
          </div>
          </div>
          <div class="advanced-row {{ 'show' if not door.isUnlocked else '' }}" id="door-adv-{{ door.id }}">
            <label class="adv-label" style="display:flex;align-items:center;gap:.4rem;cursor:pointer"><input type="checkbox" class="adv-checkbox" id="door-adv-check-{{ door.id }}" onchange="toggleDoorAdvanced('{{ door.id }}')"> Advanced</label>
            <div id="door-adv-options-{{ door.id }}" style="display:none;align-items:center;gap:.5rem;flex-wrap:wrap">
              <label class="adv-label">Unlock for:</label>
              <select class="time-select" id="door-time-{{ door.id }}" onchange="doorTimeChanged(this,'{{ door.id }}')">
                <option value="5">5 min</option><option value="15" selected>15 min</option><option value="30">30 min</option><option value="60">1 hr</option><option value="120">2 hr</option><option value="custom">Custom...</option></select>
              <input type="number" id="door-custom-time-{{ door.id }}" min="1" max="480" placeholder="min" style="display:none;width:55px" class="time-select">
              <button class="btn-timed" onclick="timedUnlockDoor('{{ door.id }}','{{ door.name }}')">&#9201; Timed Unlock</button>
            </div>
          </div>
          <div class="timer-display" id="door-timer-{{ door.id }}"><span class="timer-icon">&#9201;</span><span class="timer-text">Auto-locks in</span>
            <span class="timer-countdown" id="door-countdown-{{ door.id }}">--:--</span>
            <button class="btn-cancel-timer" onclick="cancelDoorTimer('{{ door.id }}')">Cancel &amp; Lock</button>
          </div>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  </div>

  <!-- ════ MONITOR PANEL ════ -->
  <div class="panel" id="panel-monitor">
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
          <a class="btn" href="http://{{ request.host.split(':')[0] }}:5002" target="_blank">Full Dashboard</a>
          <button class="btn" onclick="location.href=location.pathname+'?t='+Date.now()+(location.hash||'')">Refresh</button>
        </div>
      </div>
      <div class="item-list">
      {% for dev in monitors %}
        <div class="item-card {{ 'off' if not dev.online else 'on' }}">
          <div class="item-top">
          <div class="item-info">
            <div class="item-name">{{ dev.name }}</div>
            <div class="item-meta">
              {{ dev.type }}
              {% if dev.ip %}&middot; {{ dev.ip }}{% endif %}
              {% if dev.firmware %}&middot; FW: {{ dev.firmware }}{% endif %}
              {% if dev.uptime %}&middot; Up: {{ dev.uptime }}{% endif %}
            </div>
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

</div>

<div class="toast" id="toast"></div>

<script>
/* ── Tabs ── */
function switchTab(el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  const panel = el.dataset.panel;
  document.getElementById('panel-' + panel).classList.add('active');
  history.replaceState(null, '', '#' + panel);
}
// Restore tab from URL hash on load
(function() {
  const hash = location.hash.replace('#', '');
  if (hash) {
    const tab = document.querySelector('.tab[data-panel="' + hash + '"]');
    if (tab) switchTab(tab);
  }
})();

/* ── Toast ── */
function toast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + (type || 'ok');
  setTimeout(() => el.classList.remove('show'), 3000);
}

/* ── Camera controls ── */
function toggleCamAdvanced(id){const c=document.getElementById('cam-adv-check-'+id).checked;document.getElementById('cam-adv-options-'+id).style.display=c?'flex':'none'}
function camTimeChanged(sel,id){document.getElementById('cam-custom-time-'+id).style.display=sel.value==='custom'?'inline-block':'none'}

async function toggleCamera(el) {
  const id = el.dataset.id, name = el.dataset.name, turnOn = el.checked;
  const label = document.getElementById('cam-label-' + id);
  el.disabled = true; label.textContent = '...';

  try {
    const r = await fetch('/api/cameras/toggle', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ camera_id: id, enable: turnOn }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'API error');
    const isOff = data.camera ? data.camera.isOff : !turnOn;
    toast(name + ' \u2192 ' + (isOff ? 'OFF (privacy)' : 'ON'), 'ok');
    setTimeout(() => location.href=location.pathname+'?t='+Date.now()+(location.hash||''), 1200);
  } catch (err) {
    el.checked = !turnOn;
    label.textContent = turnOn ? 'off' : 'on';
    toast('Error: ' + err.message, 'err');
    el.disabled = false;
  }
}

const camCdi = {};
function startCamCountdown(id, sec) {
  const td = document.getElementById('cam-timer-' + id), cd = document.getElementById('cam-countdown-' + id);
  if (!td || !cd) return;
  td.classList.add('show');
  if (camCdi[id]) clearInterval(camCdi[id]);
  let rem = sec;
  function u() {
    if (rem <= 0) { clearInterval(camCdi[id]); td.classList.remove('show'); setTimeout(() => location.href=location.pathname+'?t='+Date.now()+(location.hash||''), 1000); return; }
    const h = Math.floor(rem/3600), m = Math.floor((rem%3600)/60), s = rem%60;
    cd.textContent = h > 0 ? h+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0') : m+':'+String(s).padStart(2,'0');
    rem--;
  }
  u(); camCdi[id] = setInterval(u, 1000);
}

async function timedOffCam(id, name) {
  const sel = document.getElementById('cam-time-' + id);
  let min = parseInt(sel.value);
  if (sel.value === 'custom') { min = parseInt(document.getElementById('cam-custom-time-' + id).value); if (!min || min < 1) { toast('Enter valid minutes', 'err'); return; } }
  try {
    const r = await fetch('/api/cameras/timed-off', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({camera_id: id, minutes: min}) });
    const d = await r.json(); if (!r.ok) throw new Error(d.error || 'API error');
    const card = document.getElementById('cam-card-' + id), label = document.getElementById('cam-label-' + id),
          toggle = document.getElementById('cam-toggle-' + id), adv = document.getElementById('cam-adv-' + id);
    card.className = 'item-card off'; label.textContent = 'off'; toggle.checked = false; if(adv) adv.classList.remove('show');
    startCamCountdown(id, min * 60);
    toast(name + ' \u2192 OFF for ' + min + ' min', 'ok');
  } catch (e) { toast('Error: ' + e.message, 'err'); }
}

async function cancelCamTimer(id) {
  try {
    const r = await fetch('/api/cameras/cancel-timer', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({camera_id: id}) });
    const d = await r.json(); if (!r.ok) throw new Error(d.error || 'API error');
    if (camCdi[id]) clearInterval(camCdi[id]); document.getElementById('cam-timer-' + id).classList.remove('show');
    toast(d.name + ' \u2192 timer cancelled, ENABLED', 'ok'); setTimeout(() => location.href=location.pathname+'?t='+Date.now()+(location.hash||''), 500);
  } catch (e) { toast('Error: ' + e.message, 'err'); }
}

async function enableAllCameras() {
  if (!confirm('Re-enable ALL cameras (and cancel all timers)?')) return;
  try {
    const r = await fetch('/api/cameras/enable-all', { method: 'POST' });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'API error');
    toast('Enabled ' + (data.changed || 0) + ' camera(s)', 'ok');
    setTimeout(() => location.href=location.pathname+'?t='+Date.now()+(location.hash||''), 800);
  } catch (err) { toast('Error: ' + err.message, 'err'); }
}

// Load active camera timers on page load
(async function(){try{const r=await fetch('/api/cameras/timers');const d=await r.json();
for(const[id,info]of Object.entries(d)){if(info.remaining_sec>0)startCamCountdown(id,info.remaining_sec)}}catch(e){}})();

/* ── Door controls ── */
function toggleDoorAdvanced(id){const c=document.getElementById('door-adv-check-'+id).checked;document.getElementById('door-adv-options-'+id).style.display=c?'flex':'none'}
function doorTimeChanged(sel,id){document.getElementById('door-custom-time-'+id).style.display=sel.value==='custom'?'inline-block':'none'}

async function toggleDoor(el) {
  const id = el.dataset.id, name = el.dataset.name, shouldLock = el.checked;
  const label = document.getElementById('door-label-' + id);
  el.disabled = true; label.textContent = '...';

  try {
    const r = await fetch('/api/doors/toggle', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ door_id: id, lock: shouldLock }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'API error');
    const isUnlocked = !shouldLock;
    toast(name + ' \u2192 ' + (isUnlocked ? 'UNLOCKED' : 'LOCKED'), 'ok');
    setTimeout(() => location.href=location.pathname+'?t='+Date.now()+(location.hash||''), 1200);
  } catch (err) {
    el.checked = !shouldLock;
    label.textContent = shouldLock ? 'unlocked' : 'locked';
    toast('Error: ' + err.message, 'err');
    el.disabled = false;
  }
}

const doorCdi = {};
function startDoorCountdown(id, sec) {
  const td = document.getElementById('door-timer-' + id), cd = document.getElementById('door-countdown-' + id);
  td.classList.add('show');
  if (doorCdi[id]) clearInterval(doorCdi[id]);
  let rem = sec;
  function u() {
    if (rem <= 0) { clearInterval(doorCdi[id]); td.classList.remove('show'); setTimeout(() => location.href=location.pathname+'?t='+Date.now()+(location.hash||''), 1000); return; }
    const h = Math.floor(rem/3600), m = Math.floor((rem%3600)/60), s = rem%60;
    cd.textContent = h > 0 ? h+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0') : m+':'+String(s).padStart(2,'0');
    rem--;
  }
  u(); doorCdi[id] = setInterval(u, 1000);
}

async function timedUnlockDoor(id, name) {
  const sel = document.getElementById('door-time-' + id);
  let min = parseInt(sel.value);
  if (sel.value === 'custom') { min = parseInt(document.getElementById('door-custom-time-' + id).value); if (!min || min < 1) { toast('Enter valid minutes', 'err'); return; } }
  try {
    const r = await fetch('/api/doors/timed-unlock', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({door_id: id, minutes: min}) });
    const d = await r.json(); if (!r.ok) throw new Error(d.error || 'API error');
    const card = document.getElementById('door-card-' + id), label = document.getElementById('door-label-' + id),
          badge = document.getElementById('door-badge-' + id), toggle = document.getElementById('door-toggle-' + id), adv = document.getElementById('door-adv-' + id);
    card.className = 'item-card unlocked'; label.textContent = 'unlocked'; badge.textContent = 'UNLOCKED'; badge.className = 'badge unlocked'; toggle.checked = false; adv.classList.remove('show');
    startDoorCountdown(id, min * 60);
    toast(name + ' \u2192 UNLOCKED for ' + min + ' min', 'ok');
  } catch (e) { toast('Error: ' + e.message, 'err'); }
}

async function cancelDoorTimer(id) {
  try {
    const r = await fetch('/api/doors/cancel-timer', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({door_id: id}) });
    const d = await r.json(); if (!r.ok) throw new Error(d.error || 'API error');
    if (doorCdi[id]) clearInterval(doorCdi[id]); document.getElementById('door-timer-' + id).classList.remove('show');
    toast(d.name + ' \u2192 timer cancelled, LOCKED', 'ok'); setTimeout(() => location.href=location.pathname+'?t='+Date.now()+(location.hash||''), 500);
  } catch (e) { toast('Error: ' + e.message, 'err'); }
}

async function lockAllDoors() {
  if (!confirm('Lock ALL doors (and cancel all timers)?')) return;
  try {
    const r = await fetch('/api/doors/lock-all', { method: 'POST' });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'API error');
    toast('Locked ' + (data.changed || 0) + ' door(s)', 'ok');
    setTimeout(() => location.href=location.pathname+'?t='+Date.now()+(location.hash||''), 800);
  } catch (err) { toast('Error: ' + err.message, 'err'); }
}

// Load active timers on page load
(async function(){try{const r=await fetch('/api/doors/timers');const d=await r.json();
for(const[id,info]of Object.entries(d)){if(info.remaining_sec>0)startDoorCountdown(id,info.remaining_sec)}}catch(e){}})();
</script>
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

    # Fetch cameras from backend
    try:
        r = requests.get(f"{config.CAMERA_BACKEND}/", timeout=BACKEND_TIMEOUT)
        # We need the API data, not the HTML. Hit the backend's list endpoint
        # by scraping the same data the backend uses. We'll add a lightweight
        # JSON endpoint to proxy through instead.
    except Exception:
        pass

    # Actually, let's just call the backends' pages and parse —
    # better to add a /api/list endpoint. For now, we proxy the
    # existing API structure.

    # Camera data: the camera backend renders HTML at / but we need JSON.
    # We'll call its internal API indirectly by hitting the toggle endpoint
    # with a GET-style list. Since the camera app doesn't have a list API,
    # we add one via proxy.
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
