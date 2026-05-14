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

audit_helper.init("/var/log/unifi-camera-audit.log")

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
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Camera Privacy Toggle{% if group_name != 'default' %} — {{ group_name }}{% endif %}</title><style>
:root{--bg:#0f1114;--surface:#1a1d23;--border:#2a2d35;--text:#e0e0e0;--muted:#888;--accent:#3b82f6;--danger:#ef4444;--success:#22c55e;--warn:#f59e0b}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:2rem 1rem}
.container{max-width:720px;margin:0 auto}
h1{font-size:1.4rem;font-weight:600;margin-bottom:.25rem}
.subtitle{color:var(--muted);font-size:.85rem;margin-bottom:1.5rem}
.group-label{display:inline-block;background:var(--accent);color:#fff;font-size:.7rem;font-weight:600;padding:.15rem .5rem;border-radius:4px;margin-left:.5rem;text-transform:uppercase;vertical-align:middle}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;gap:1rem;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1rem;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:.85rem;cursor:pointer;transition:background .15s}
.btn:hover{background:#252830}
.camera-list{display:flex;flex-direction:column;gap:.5rem}
.camera-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:.9rem 1.1rem;transition:border-color .2s}
.camera-card.off{border-left:3px solid var(--danger)}.camera-card.on{border-left:3px solid var(--success)}
.cam-top{display:flex;align-items:center;justify-content:space-between}
.cam-info{flex:1;min-width:0}.cam-name{font-weight:600;font-size:.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cam-meta{font-size:.75rem;color:var(--muted);margin-top:.15rem}
.toggle-wrap{flex-shrink:0;margin-left:1rem;display:flex;align-items:center;gap:.5rem}
.toggle-label{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.switch{position:relative;width:44px;height:24px}.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;inset:0;background:var(--danger);border-radius:24px;cursor:pointer;transition:background .25s}
.slider::before{content:"";position:absolute;left:3px;bottom:3px;width:18px;height:18px;background:#fff;border-radius:50%;transition:transform .25s}
.switch input:checked+.slider{background:var(--success)}.switch input:checked+.slider::before{transform:translateX(20px)}
.switch input:disabled+.slider{opacity:.4;cursor:not-allowed}
.badge{display:inline-block;font-size:.65rem;padding:.1rem .4rem;border-radius:3px;font-weight:600;text-transform:uppercase}
.badge.connected{background:rgba(34,197,94,.15);color:var(--success)}.badge.disconnected{background:rgba(239,68,68,.15);color:var(--danger)}
.advanced-row{display:none;align-items:center;gap:.6rem;margin-top:.7rem;padding-top:.7rem;border-top:1px solid var(--border);flex-wrap:wrap}
.advanced-row.show{display:flex}
.adv-label{font-size:.75rem;color:var(--muted)}.adv-checkbox{cursor:pointer;accent-color:var(--accent)}
.time-select{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:.3rem .5rem;font-size:.8rem}
.time-select:focus{border-color:var(--accent);outline:none}
.btn-timed{padding:.3rem .8rem;font-size:.78rem;border:1px solid var(--accent);border-radius:5px;background:rgba(59,130,246,.1);color:var(--accent);cursor:pointer;transition:background .15s}
.btn-timed:hover{background:rgba(59,130,246,.2)}
.timer-display{display:none;align-items:center;gap:.5rem;margin-top:.6rem;padding:.5rem .8rem;background:rgba(59,130,246,.06);border:1px solid rgba(59,130,246,.2);border-radius:6px}
.timer-display.show{display:flex}.timer-icon{font-size:1rem}.timer-text{font-size:.8rem;color:var(--accent)}
.timer-countdown{font-size:.85rem;font-weight:600;color:var(--accent);font-variant-numeric:tabular-nums}
.btn-cancel-timer{margin-left:auto;padding:.2rem .6rem;font-size:.72rem;border:1px solid var(--danger);border-radius:4px;background:transparent;color:var(--danger);cursor:pointer}
.btn-cancel-timer:hover{background:rgba(239,68,68,.1)}
.toast{position:fixed;top:1rem;right:1rem;padding:.7rem 1.2rem;border-radius:6px;font-size:.85rem;font-weight:500;color:#fff;opacity:0;transform:translateY(-10px);transition:opacity .3s,transform .3s;z-index:99;pointer-events:none}
.toast.show{opacity:1;transform:translateY(0)}.toast.ok{background:var(--success)}.toast.err{background:var(--danger)}
.error-box{padding:1.5rem;background:rgba(239,68,68,.08);border:1px solid var(--danger);border-radius:8px;color:var(--danger);font-size:.9rem}
</style></head><body>
<div class="container">
<h1>Camera Privacy Toggle{% if group_name != 'default' %}<span class="group-label">{{ group_name }}</span>{% endif %}</h1>
<p class="subtitle">{{ host }} &mdash; Toggle cameras off for privacy, back on when done.</p>
{% if error %}<div class="error-box">{{ error }}</div>{% else %}
<div class="topbar">
<span style="font-size:.8rem;color:var(--muted)">{{ cameras|length }} camera{{ 's' if cameras|length != 1 }} &middot; {{ cameras|selectattr('isOff')|list|length }} off</span>
<div><button class="btn" onclick="location.href=location.pathname+'?t='+Date.now()+(location.hash||'')">Refresh</button></div>
</div>
<div class="camera-list">
{% for cam in cameras %}
<div class="camera-card {{ 'off' if cam.isOff else 'on' }}" id="card-{{ cam.id }}">
<div class="cam-top">
<div class="cam-info"><div class="cam-name">{{ cam.name }}</div>
<div class="cam-meta">{{ cam.type }} &middot; <span class="badge {{ 'connected' if cam.state == 'CONNECTED' else 'disconnected' }}" id="badge-{{ cam.id }}">{{ cam.state }}</span> &middot; Mode: <strong id="mode-{{ cam.id }}">{{ cam.recordingMode }}</strong>{% if cam.host %} &middot; {{ cam.host }}{% endif %}</div></div>
<div class="toggle-wrap"><span class="toggle-label" id="label-{{ cam.id }}">{{ 'off' if cam.isOff else 'on' }}</span>
<label class="switch"><input type="checkbox" id="toggle-{{ cam.id }}" data-id="{{ cam.id }}" data-name="{{ cam.name }}" {{ '' if cam.isOff else 'checked' }} onchange="toggleCamera(this)"><span class="slider"></span></label></div>
</div>
<div class="advanced-row {{ 'show' if not cam.isOff else '' }}" id="adv-{{ cam.id }}">
<label class="adv-label" style="display:flex;align-items:center;gap:.4rem;cursor:pointer"><input type="checkbox" class="adv-checkbox" id="adv-check-{{ cam.id }}" onchange="toggleAdvanced('{{ cam.id }}')"> Advanced</label>
<div id="adv-options-{{ cam.id }}" style="display:none;align-items:center;gap:.5rem;flex-wrap:wrap">
<label class="adv-label">Privacy for:</label>
<select class="time-select" id="time-{{ cam.id }}" onchange="timeChanged(this,'{{ cam.id }}')">
<option value="5">5 min</option><option value="15" selected>15 min</option><option value="30">30 min</option><option value="60">1 hour</option><option value="120">2 hours</option><option value="custom">Custom...</option></select>
<input type="number" id="custom-time-{{ cam.id }}" min="1" max="480" placeholder="min" style="display:none;width:60px" class="time-select">
<input type="text" id="reason-{{ cam.id }}" class="time-select" placeholder="Reason (optional)" style="flex:1;min-width:120px">
<button class="btn-timed" onclick="timedOff('{{ cam.id }}','{{ cam.name }}')">&#9201; Timed Privacy</button>
</div></div>
<div class="timer-display" id="timer-{{ cam.id }}"><span class="timer-icon">&#9201;</span><span class="timer-text">Auto-enables in</span>
<span class="timer-countdown" id="countdown-{{ cam.id }}">--:--</span>
<button class="btn-cancel-timer" onclick="cancelTimer('{{ cam.id }}')">Cancel &amp; Enable</button></div>
</div>
{% endfor %}
</div>{% endif %}
</div>
<div class="toast" id="toast"></div>
<script>
function toast(m,t){const e=document.getElementById('toast');e.textContent=m;e.className='toast show '+(t||'ok');setTimeout(()=>e.classList.remove('show'),3000)}
function toggleAdvanced(id){const c=document.getElementById('adv-check-'+id).checked;document.getElementById('adv-options-'+id).style.display=c?'flex':'none'}
function timeChanged(sel,id){document.getElementById('custom-time-'+id).style.display=sel.value==='custom'?'inline-block':'none'}

async function toggleCamera(el){const id=el.dataset.id,name=el.dataset.name,turnOn=el.checked;
const label=document.getElementById('label-'+id);
el.disabled=true;label.textContent='...';
try{const r=await fetch('/api/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({camera_id:id,enable:turnOn,reason:document.getElementById('reason-'+id)?document.getElementById('reason-'+id).value:''})});
const d=await r.json();if(!r.ok)throw new Error(d.error||'API error');
const isOff=d.camera.isOff;
toast(name+' \u2192 '+(isOff?'OFF (privacy)':'ON'),'ok');
setTimeout(()=>location.href=location.pathname+'?t='+Date.now()+(location.hash||''),1200)}
catch(e){el.checked=!turnOn;label.textContent=turnOn?'off':'on';toast('Error: '+e.message,'err');el.disabled=false}}

const cdi={};
function startCountdown(id,sec){const td=document.getElementById('timer-'+id),cd=document.getElementById('countdown-'+id);td.classList.add('show');
if(cdi[id])clearInterval(cdi[id]);let rem=sec;
function u(){if(rem<=0){clearInterval(cdi[id]);td.classList.remove('show');setTimeout(()=>location.href=location.pathname+'?t='+Date.now()+(location.hash||''),1000);return}
const h=Math.floor(rem/3600),m=Math.floor((rem%3600)/60),s=rem%60;
cd.textContent=h>0?h+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0'):m+':'+String(s).padStart(2,'0');rem--}
u();cdi[id]=setInterval(u,1000)}

async function timedOff(id,name){const sel=document.getElementById('time-'+id);let min=parseInt(sel.value);
if(sel.value==='custom'){min=parseInt(document.getElementById('custom-time-'+id).value);if(!min||min<1){toast('Enter valid minutes','err');return}}
try{const r=await fetch('/api/timed-off',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({camera_id:id,minutes:min,reason:document.getElementById('reason-'+id)?document.getElementById('reason-'+id).value:''})});
const d=await r.json();if(!r.ok)throw new Error(d.error||'API error');
const card=document.getElementById('card-'+id),label=document.getElementById('label-'+id),badge=document.getElementById('badge-'+id),mode=document.getElementById('mode-'+id),toggle=document.getElementById('toggle-'+id),adv=document.getElementById('adv-'+id);
card.className='camera-card off';label.textContent='off';if(badge){badge.textContent='OFF';badge.className='badge disconnected'}
if(mode)mode.textContent='never';toggle.checked=false;adv.classList.remove('show');
startCountdown(id,min*60);toast(name+' \u2192 OFF for '+min+' min','ok')}
catch(e){toast('Error: '+e.message,'err')}}

async function cancelTimer(id){try{const r=await fetch('/api/cancel-timer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({camera_id:id,reason:'Timer cancelled'})});
const d=await r.json();if(!r.ok)throw new Error(d.error||'API error');
if(cdi[id])clearInterval(cdi[id]);document.getElementById('timer-'+id).classList.remove('show');
toast(d.name+' \u2192 timer cancelled, ENABLED','ok');setTimeout(()=>location.href=location.pathname+'?t='+Date.now()+(location.hash||''),500)}
catch(e){toast('Error: '+e.message,'err')}}

(async function(){try{const r=await fetch('/api/timers');const d=await r.json();
for(const[id,info]of Object.entries(d)){if(info.remaining_sec>0)startCountdown(id,info.remaining_sec)}}catch(e){}})();
</script></body></html>"""

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
