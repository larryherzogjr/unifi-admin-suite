"""
Flask web UI for toggling UniFi Access door locks.

Features:
  - Toggle individual doors locked/unlocked
  - Advanced mode: timed unlock with automatic re-lock
  - Lock All safety button
  - Portal integration via /api/list

Run:  python app.py
Then visit http://your-server:5001
"""

import logging
import threading
from datetime import datetime, timedelta

from flask import Flask, render_template_string, request, jsonify

import config
import access_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("app")
app = Flask(__name__)

# ── Timed unlock tracking ──
timed_unlocks = {}   # { door_id: { name, unlock_at, lock_at, duration_min, timer } }
timed_lock = threading.Lock()

def _auto_lock(door_id, door_name):
    log.info("Timer expired for %s (%s) — auto-locking", door_name, door_id)
    try:
        access_api.lock_door(door_id)
        log.info("Auto-locked %s successfully", door_name)
    except Exception:
        log.exception("Auto-lock FAILED for %s — safety net will catch it", door_name)
    finally:
        with timed_lock:
            timed_unlocks.pop(door_id, None)

def start_timed_unlock(door_id, door_name, minutes):
    cancel_timer(door_id)
    access_api.unlock_door(door_id)
    timer = threading.Timer(minutes * 60, _auto_lock, args=[door_id, door_name])
    timer.daemon = True
    timer.start()
    with timed_lock:
        timed_unlocks[door_id] = {
            "name": door_name,
            "unlock_at": datetime.now(),
            "lock_at": datetime.now() + timedelta(minutes=minutes),
            "duration_min": minutes,
            "timer": timer,
        }
    log.info("Timed unlock: %s for %d min (auto-lock at %s)", door_name, minutes,
             (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M:%S"))

def cancel_timer(door_id):
    with timed_lock:
        entry = timed_unlocks.pop(door_id, None)
    if entry and entry["timer"]:
        entry["timer"].cancel()
        log.info("Cancelled timer for %s", entry["name"])

def get_active_timers():
    now = datetime.now()
    result = {}
    with timed_lock:
        for did, e in timed_unlocks.items():
            rem = (e["lock_at"] - now).total_seconds()
            if rem > 0:
                result[did] = {"name": e["name"], "remaining_sec": int(rem),
                               "duration_min": e["duration_min"], "lock_at": e["lock_at"].strftime("%H:%M:%S")}
    return result

# ── HTML Template ──
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Door Lock Toggle</title><style>
:root{--bg:#0f1114;--surface:#1a1d23;--border:#2a2d35;--text:#e0e0e0;--muted:#888;--accent:#3b82f6;--danger:#ef4444;--success:#22c55e;--warn:#f59e0b}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:2rem 1rem}
.container{max-width:720px;margin:0 auto}
h1{font-size:1.4rem;font-weight:600;margin-bottom:.25rem}
.subtitle{color:var(--muted);font-size:.85rem;margin-bottom:1.5rem}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;gap:1rem;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1rem;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:.85rem;cursor:pointer;transition:background .15s}
.btn:hover{background:#252830}.btn.success{border-color:var(--success);color:var(--success)}.btn.success:hover{background:rgba(34,197,94,.12)}
.door-list{display:flex;flex-direction:column;gap:.5rem}
.door-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:.9rem 1.1rem;transition:border-color .2s}
.door-card.unlocked{border-left:3px solid var(--warn)}.door-card.locked{border-left:3px solid var(--success)}
.door-top{display:flex;align-items:center;justify-content:space-between}
.door-info{flex:1;min-width:0}.door-name{font-weight:600;font-size:.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.door-meta{font-size:.75rem;color:var(--muted);margin-top:.15rem}
.toggle-wrap{flex-shrink:0;margin-left:1rem;display:flex;align-items:center;gap:.5rem}
.toggle-label{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;min-width:60px;text-align:right}
.switch{position:relative;width:44px;height:24px}.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;inset:0;background:var(--warn);border-radius:24px;cursor:pointer;transition:background .25s}
.slider::before{content:"";position:absolute;left:3px;bottom:3px;width:18px;height:18px;background:#fff;border-radius:50%;transition:transform .25s}
.switch input:checked+.slider{background:var(--success)}.switch input:checked+.slider::before{transform:translateX(20px)}
.switch input:disabled+.slider{opacity:.4;cursor:not-allowed}
.badge{display:inline-block;font-size:.65rem;padding:.1rem .4rem;border-radius:3px;font-weight:600;text-transform:uppercase}
.badge.locked{background:rgba(34,197,94,.15);color:var(--success)}.badge.unlocked{background:rgba(245,158,11,.15);color:var(--warn)}
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
.toast.show{opacity:1;transform:translateY(0)}.toast.ok{background:var(--success)}.toast.err{background:var(--danger)}.toast.warn{background:var(--warn);color:#000}
.error-box{padding:1.5rem;background:rgba(239,68,68,.08);border:1px solid var(--danger);border-radius:8px;color:var(--danger);font-size:.9rem}
</style></head><body>
<div class="container">
<h1>Door Lock Toggle</h1>
<p class="subtitle">{{ host }}:{{ port }} &mdash; Unlock doors temporarily, lock when done.</p>
{% if error %}<div class="error-box">{{ error }}</div>{% else %}
<div class="topbar">
<span style="font-size:.8rem;color:var(--muted)">{{ doors|length }} door{{ 's' if doors|length != 1 }} &middot; {{ doors|selectattr('isUnlocked')|list|length }} unlocked</span>
<div><button class="btn success" onclick="lockAll()">Lock All</button> <button class="btn" onclick="location.reload()">Refresh</button></div>
</div>
<div class="door-list">
{% for door in doors %}
<div class="door-card {{ 'unlocked' if door.isUnlocked else 'locked' }}" id="card-{{ door.id }}">
<div class="door-top">
<div class="door-info"><div class="door-name">{{ door.name }}</div>
<div class="door-meta">{% if door.type %}{{ door.type }} &middot; {% endif %}<span class="badge {{ 'unlocked' if door.isUnlocked else 'locked' }}" id="badge-{{ door.id }}">{{ 'UNLOCKED' if door.isUnlocked else 'LOCKED' }}</span> &middot; Rule: <strong>{{ door.lockRule }}</strong></div></div>
<div class="toggle-wrap"><span class="toggle-label" id="label-{{ door.id }}">{{ 'unlocked' if door.isUnlocked else 'locked' }}</span>
<label class="switch"><input type="checkbox" id="toggle-{{ door.id }}" data-id="{{ door.id }}" data-name="{{ door.name }}" {{ '' if door.isUnlocked else 'checked' }} onchange="toggleDoor(this)"><span class="slider"></span></label></div></div>
<div class="advanced-row {{ 'show' if not door.isUnlocked else '' }}" id="adv-{{ door.id }}">
<label class="adv-label" style="display:flex;align-items:center;gap:.4rem;cursor:pointer"><input type="checkbox" class="adv-checkbox" id="adv-check-{{ door.id }}" onchange="toggleAdvanced('{{ door.id }}')"> Advanced</label>
<div id="adv-options-{{ door.id }}" style="display:none;align-items:center;gap:.5rem;flex-wrap:wrap">
<label class="adv-label">Unlock for:</label>
<select class="time-select" id="time-{{ door.id }}" onchange="timeChanged(this,'{{ door.id }}')">
<option value="5">5 min</option><option value="15" selected>15 min</option><option value="30">30 min</option><option value="60">1 hour</option><option value="120">2 hours</option><option value="custom">Custom...</option></select>
<input type="number" id="custom-time-{{ door.id }}" min="1" max="480" placeholder="min" style="display:none;width:60px" class="time-select">
<button class="btn-timed" onclick="timedUnlock('{{ door.id }}','{{ door.name }}')">&#9201; Timed Unlock</button>
</div></div>
<div class="timer-display" id="timer-{{ door.id }}"><span class="timer-icon">&#9201;</span><span class="timer-text">Auto-locks in</span>
<span class="timer-countdown" id="countdown-{{ door.id }}">--:--</span>
<button class="btn-cancel-timer" onclick="cancelTimer('{{ door.id }}')">Cancel &amp; Lock</button></div>
</div>
{% endfor %}
</div>{% endif %}
</div>
<div class="toast" id="toast"></div>
<script>
function toast(m,t){const e=document.getElementById('toast');e.textContent=m;e.className='toast show '+(t||'ok');setTimeout(()=>e.classList.remove('show'),3000)}
function toggleAdvanced(id){const c=document.getElementById('adv-check-'+id).checked;document.getElementById('adv-options-'+id).style.display=c?'flex':'none'}
function timeChanged(sel,id){document.getElementById('custom-time-'+id).style.display=sel.value==='custom'?'inline-block':'none'}
async function toggleDoor(el){const id=el.dataset.id,name=el.dataset.name,shouldLock=el.checked;
const label=document.getElementById('label-'+id),card=document.getElementById('card-'+id),badge=document.getElementById('badge-'+id),adv=document.getElementById('adv-'+id),tmr=document.getElementById('timer-'+id);
el.disabled=true;label.textContent='...';
try{const r=await fetch('/api/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({door_id:id,lock:shouldLock})});
const d=await r.json();if(!r.ok)throw new Error(d.error||'API error');
const u=!shouldLock;label.textContent=u?'unlocked':'locked';card.className='door-card '+(u?'unlocked':'locked');
badge.textContent=u?'UNLOCKED':'LOCKED';badge.className='badge '+(u?'unlocked':'locked');
adv.classList.toggle('show',!u);if(shouldLock)tmr.classList.remove('show');
toast(name+' \u2192 '+(u?'UNLOCKED':'LOCKED'),'ok')}
catch(e){el.checked=!shouldLock;label.textContent=shouldLock?'unlocked':'locked';toast('Error: '+e.message,'err')}
finally{el.disabled=false}}
async function timedUnlock(id,name){const sel=document.getElementById('time-'+id);let min=parseInt(sel.value);
if(sel.value==='custom'){min=parseInt(document.getElementById('custom-time-'+id).value);if(!min||min<1){toast('Enter valid minutes','err');return}}
try{const r=await fetch('/api/timed-unlock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({door_id:id,minutes:min})});
const d=await r.json();if(!r.ok)throw new Error(d.error||'API error');
const card=document.getElementById('card-'+id),label=document.getElementById('label-'+id),badge=document.getElementById('badge-'+id),toggle=document.getElementById('toggle-'+id),adv=document.getElementById('adv-'+id);
card.className='door-card unlocked';label.textContent='unlocked';badge.textContent='UNLOCKED';badge.className='badge unlocked';toggle.checked=false;adv.classList.remove('show');
startCountdown(id,min*60);toast(name+' \u2192 UNLOCKED for '+min+' min','ok')}
catch(e){toast('Error: '+e.message,'err')}}
const cdi={};
function startCountdown(id,sec){const td=document.getElementById('timer-'+id),cd=document.getElementById('countdown-'+id);td.classList.add('show');
if(cdi[id])clearInterval(cdi[id]);let rem=sec;
function u(){if(rem<=0){clearInterval(cdi[id]);td.classList.remove('show');setTimeout(()=>location.reload(),1000);return}
const h=Math.floor(rem/3600),m=Math.floor((rem%3600)/60),s=rem%60;
cd.textContent=h>0?h+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0'):m+':'+String(s).padStart(2,'0');rem--}
u();cdi[id]=setInterval(u,1000)}
async function cancelTimer(id){try{const r=await fetch('/api/cancel-timer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({door_id:id})});
const d=await r.json();if(!r.ok)throw new Error(d.error||'API error');
if(cdi[id])clearInterval(cdi[id]);document.getElementById('timer-'+id).classList.remove('show');
toast(d.name+' \u2192 timer cancelled, LOCKED','ok');setTimeout(()=>location.reload(),500)}
catch(e){toast('Error: '+e.message,'err')}}
async function lockAll(){if(!confirm('Lock ALL doors (and cancel all timers)?'))return;
try{const r=await fetch('/api/lock-all',{method:'POST'});const d=await r.json();if(!r.ok)throw new Error(d.error||'API error');
toast('Locked '+d.changed+' door(s)','ok');setTimeout(()=>location.reload(),800)}catch(e){toast('Error: '+e.message,'err')}}
(async function(){try{const r=await fetch('/api/timers');const d=await r.json();
for(const[id,info]of Object.entries(d)){if(info.remaining_sec>0)startCountdown(id,info.remaining_sec)}}catch(e){}})();
</script></body></html>"""

# ── Routes ──
@app.route("/")
def index():
    try:
        doors = [access_api.door_summary(d) for d in access_api.list_doors()]
        return render_template_string(PAGE_TEMPLATE, doors=doors, error=None, host=config.ACCESS_HOST, port=config.ACCESS_PORT)
    except Exception as exc:
        log.exception("Failed to load doors")
        return render_template_string(PAGE_TEMPLATE, doors=[], error=str(exc), host=config.ACCESS_HOST, port=config.ACCESS_PORT)

@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    data = request.get_json(force=True)
    door_id = data.get("door_id")
    should_lock = data.get("lock", True)
    if not door_id: return jsonify({"error": "door_id required"}), 400
    try:
        if should_lock:
            cancel_timer(door_id)
            access_api.lock_door(door_id)
        else:
            access_api.unlock_door(door_id)
        return jsonify({"ok": True, "locked": should_lock})
    except Exception as exc:
        log.exception("Toggle failed for %s", door_id)
        return jsonify({"error": str(exc)}), 500

@app.route("/api/timed-unlock", methods=["POST"])
def api_timed_unlock():
    data = request.get_json(force=True)
    door_id = data.get("door_id")
    minutes = data.get("minutes")
    if not door_id: return jsonify({"error": "door_id required"}), 400
    if not minutes or not isinstance(minutes, (int, float)) or minutes < 1:
        return jsonify({"error": "minutes must be a positive number"}), 400
    if minutes > 480: return jsonify({"error": "max 8 hours (480 min)"}), 400
    minutes = int(minutes)
    try:
        doors = access_api.list_doors()
        door_name = "Unknown"
        for d in doors:
            s = access_api.door_summary(d)
            if s["id"] == door_id: door_name = s["name"]; break
        start_timed_unlock(door_id, door_name, minutes)
        return jsonify({"ok": True, "door_id": door_id, "name": door_name, "minutes": minutes,
                        "lock_at": (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M:%S")})
    except Exception as exc:
        log.exception("Timed unlock failed for %s", door_id)
        return jsonify({"error": str(exc)}), 500

@app.route("/api/cancel-timer", methods=["POST"])
def api_cancel_timer():
    data = request.get_json(force=True)
    door_id = data.get("door_id")
    if not door_id: return jsonify({"error": "door_id required"}), 400
    try:
        entry = timed_unlocks.get(door_id, {})
        door_name = entry.get("name", "Unknown")
        cancel_timer(door_id)
        access_api.lock_door(door_id)
        return jsonify({"ok": True, "name": door_name})
    except Exception as exc:
        log.exception("Cancel timer failed for %s", door_id)
        return jsonify({"error": str(exc)}), 500

@app.route("/api/timers")
def api_timers():
    return jsonify(get_active_timers())

@app.route("/api/lock-all", methods=["POST"])
def api_lock_all():
    try:
        with timed_lock:
            for did in list(timed_unlocks.keys()): cancel_timer(did)
        changed = access_api.ensure_all_doors_locked()
        return jsonify({"ok": True, "changed": len(changed), "doors": changed})
    except Exception as exc:
        log.exception("Lock-all failed")
        return jsonify({"error": str(exc)}), 500

@app.route("/api/list")
def api_list():
    try:
        doors = [access_api.door_summary(d) for d in access_api.list_doors()]
        timers = get_active_timers()
        for d in doors:
            if d["id"] in timers: d["timer"] = timers[d["id"]]
        return jsonify({"ok": True, "doors": doors})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

if __name__ == "__main__":
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
