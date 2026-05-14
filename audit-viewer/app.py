"""
Audit Log Viewer — read-only dashboard for UniFi admin action logs.

Reads JSON-lines audit logs from Camera Privacy Toggle and Door Lock Toggle,
presents them in a combined, searchable, filterable view.

Run:  python app.py
Then visit http://your-server:5004
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("app")
app = Flask(__name__)

# ── Action metadata for display ──
ACTION_META = {
    "camera_off":               {"label": "Camera Off",        "icon": "🔴", "color": "#ef4444", "category": "camera"},
    "camera_on":                {"label": "Camera On",         "icon": "🟢", "color": "#22c55e", "category": "camera"},
    "timed_camera_off":         {"label": "Timed Camera Off",  "icon": "⏱️", "color": "#3b82f6", "category": "camera"},
    "cancel_timer_camera_on":   {"label": "Timer Cancelled",   "icon": "⏹️", "color": "#f59e0b", "category": "camera"},
    "enable_all_cameras":       {"label": "Enable All Cams",   "icon": "🟢", "color": "#22c55e", "category": "camera"},
    "door_unlock":              {"label": "Door Unlock",       "icon": "🔓", "color": "#ef4444", "category": "door"},
    "door_lock":                {"label": "Door Lock",         "icon": "🔒", "color": "#22c55e", "category": "door"},
    "timed_door_unlock":        {"label": "Timed Unlock",      "icon": "⏱️", "color": "#3b82f6", "category": "door"},
    "cancel_timer_door_lock":   {"label": "Timer Cancelled",   "icon": "⏹️", "color": "#f59e0b", "category": "door"},
    "lock_all_doors":           {"label": "Lock All Doors",    "icon": "🔒", "color": "#22c55e", "category": "door"},
}

def _read_log(filepath, source_label):
    """Read a JSON-lines log file and return parsed entries."""
    entries = []
    path = Path(filepath)
    if not path.exists():
        return entries
    try:
        with open(path, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry["_source"] = source_label
                    entries.append(entry)
                except json.JSONDecodeError:
                    log.warning("Skipping malformed line %d in %s", line_num, filepath)
    except Exception:
        log.exception("Error reading %s", filepath)
    return entries

def _load_all_entries(days=None):
    """Load entries from both logs, optionally filtered by date range."""
    cam_entries = _read_log(config.CAMERA_AUDIT_LOG, "camera")
    door_entries = _read_log(config.ACCESS_AUDIT_LOG, "door")
    all_entries = cam_entries + door_entries

    # Parse timestamps and sort newest first
    for e in all_entries:
        try:
            e["_dt"] = datetime.fromisoformat(e.get("timestamp", ""))
        except (ValueError, TypeError):
            e["_dt"] = datetime.min

    all_entries.sort(key=lambda e: e["_dt"], reverse=True)

    # Filter by date range
    if days:
        cutoff = datetime.now() - timedelta(days=days)
        all_entries = [e for e in all_entries if e["_dt"] >= cutoff]

    return all_entries

# ── HTML Template ──
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audit Log Viewer</title><style>
:root{--bg:#0f1114;--surface:#1a1d23;--border:#2a2d35;--text:#e0e0e0;--muted:#888;--accent:#3b82f6;--danger:#ef4444;--success:#22c55e;--warn:#f59e0b}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:2rem 1rem}
.container{max-width:900px;margin:0 auto}
h1{font-size:1.4rem;font-weight:600;margin-bottom:.25rem}
h1 span{color:var(--accent)}
.subtitle{color:var(--muted);font-size:.85rem;margin-bottom:1.2rem}
.controls{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1rem;align-items:center}
.search-box{flex:1;min-width:200px;padding:.5rem .8rem;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.85rem}
.search-box:focus{border-color:var(--accent);outline:none}
.filter-btn{padding:.4rem .8rem;border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--muted);font-size:.78rem;cursor:pointer;transition:all .15s}
.filter-btn:hover{background:#252830}
.filter-btn.active{color:var(--accent);border-color:var(--accent);background:rgba(59,130,246,.08)}
.stats{font-size:.8rem;color:var(--muted);margin-bottom:.8rem}
.entry-list{display:flex;flex-direction:column;gap:.4rem}
.entry-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:.75rem 1rem;transition:border-color .2s}
.entry-top{display:flex;align-items:flex-start;justify-content:space-between;gap:.8rem}
.entry-action{display:flex;align-items:center;gap:.5rem}
.action-icon{font-size:1.1rem}
.action-label{font-weight:600;font-size:.85rem}
.entry-target{font-size:.9rem;font-weight:500;color:var(--text)}
.entry-time{font-size:.75rem;color:var(--muted);white-space:nowrap}
.entry-details{display:flex;flex-wrap:wrap;gap:.4rem .8rem;margin-top:.4rem;font-size:.75rem;color:var(--muted)}
.entry-details .label{color:#666}.entry-details .val{color:var(--text)}
.entry-reason{margin-top:.35rem;font-size:.8rem;color:var(--text);font-style:italic;padding:.3rem .6rem;background:rgba(59,130,246,.05);border-left:2px solid var(--accent);border-radius:0 4px 4px 0}
.badge-cat{display:inline-block;font-size:.6rem;padding:.1rem .35rem;border-radius:3px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.badge-cat.camera{background:rgba(59,130,246,.15);color:var(--accent)}
.badge-cat.door{background:rgba(245,158,11,.15);color:var(--warn)}
.empty-state{text-align:center;padding:3rem;color:var(--muted);font-size:.9rem}
.btn{padding:.4rem .8rem;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:.82rem;cursor:pointer;transition:background .15s}
.btn:hover{background:#252830}
.highlight{background:rgba(245,158,11,.25);border-radius:2px;padding:0 1px}
</style></head><body>
<div class="container">
<h1><span>UniFi</span> Audit Log</h1>
<p class="subtitle">Camera and door action history — read-only</p>

<div class="controls">
<input type="text" class="search-box" id="search" placeholder="Search by target, reason, IP, hostname..." oninput="filterEntries()">
<div class="filter-btn active" data-filter="all" onclick="setFilter(this)">All</div>
<div class="filter-btn" data-filter="camera" onclick="setFilter(this)">Cameras</div>
<div class="filter-btn" data-filter="door" onclick="setFilter(this)">Doors</div>
<div style="display:flex;gap:.3rem;align-items:center">
<div class="filter-btn {{ 'active' if days == 1 else '' }}" onclick="setDays(1)">Today</div>
<div class="filter-btn {{ 'active' if days == 7 else '' }}" onclick="setDays(7)">7 days</div>
<div class="filter-btn {{ 'active' if days == 30 else '' }}" onclick="setDays(30)">30 days</div>
<div class="filter-btn {{ 'active' if days == 0 else '' }}" onclick="setDays(0)">All time</div>
</div>
<button class="btn" onclick="location.href=location.pathname+'?days={{ days }}&t='+Date.now()">Refresh</button>
</div>

<div class="stats" id="stats">{{ entries | length }} entries</div>

<div class="entry-list" id="entry-list">
{% if entries | length == 0 %}
<div class="empty-state">No audit entries found for this time period.</div>
{% endif %}
{% for e in entries %}
<div class="entry-card" data-category="{{ e._meta.category }}" data-searchable="{{ e.target|lower }} {{ e.reason|lower }} {{ e.client_ip|lower }} {{ e.client_host|lower }} {{ e.action|lower }}">
<div class="entry-top">
<div class="entry-action">
<span class="action-icon">{{ e._meta.icon }}</span>
<span class="action-label" style="color:{{ e._meta.color }}">{{ e._meta.label }}</span>
<span class="badge-cat {{ e._meta.category }}">{{ e._meta.category }}</span>
</div>
<span class="entry-time">{{ e._display_time }}</span>
</div>
<div style="margin-top:.3rem">
<span class="entry-target">{{ e.target }}</span>
{% if e.duration_min %}<span style="font-size:.75rem;color:var(--accent)"> · {{ e.duration_min }} min</span>{% endif %}
</div>
{% if e.reason %}
<div class="entry-reason">{{ e.reason }}</div>
{% endif %}
<div class="entry-details">
<span><span class="label">IP:</span> <span class="val">{{ e.client_ip }}</span></span>
<span><span class="label">Host:</span> <span class="val">{{ e.client_host }}</span></span>
{% if e.client_ua and e.client_ua != 'unknown' %}
<span><span class="label">Client:</span> <span class="val">{{ e._short_ua }}</span></span>
{% endif %}
</div>
</div>
{% endfor %}
</div>
</div>

<script>
let activeFilter = 'all';

function setFilter(el) {
  document.querySelectorAll('.filter-btn[data-filter]').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  activeFilter = el.dataset.filter;
  filterEntries();
}

function setDays(d) {
  location.href = location.pathname + '?days=' + d;
}

function filterEntries() {
  const query = document.getElementById('search').value.toLowerCase();
  const cards = document.querySelectorAll('.entry-card');
  let shown = 0;
  cards.forEach(card => {
    const cat = card.dataset.category;
    const text = card.dataset.searchable;
    const matchCat = activeFilter === 'all' || cat === activeFilter;
    const matchSearch = !query || text.includes(query);
    const visible = matchCat && matchSearch;
    card.style.display = visible ? '' : 'none';
    if (visible) shown++;
  });
  document.getElementById('stats').textContent = shown + ' of {{ entries | length }} entries';
}
</script>
</body></html>"""

def _shorten_ua(ua):
    """Extract a short browser/OS string from User-Agent."""
    if not ua or ua == "unknown":
        return ""
    parts = []
    if "Mac" in ua: parts.append("macOS")
    elif "Windows" in ua: parts.append("Windows")
    elif "Linux" in ua: parts.append("Linux")
    elif "Android" in ua: parts.append("Android")
    elif "iPhone" in ua or "iPad" in ua: parts.append("iOS")

    if "Chrome" in ua and "Edg" not in ua: parts.append("Chrome")
    elif "Firefox" in ua: parts.append("Firefox")
    elif "Safari" in ua and "Chrome" not in ua: parts.append("Safari")
    elif "Edg" in ua: parts.append("Edge")

    return " / ".join(parts) if parts else ua[:40]

# ── Routes ──
@app.route("/")
def index():
    days_param = request.args.get("days", str(config.DEFAULT_DAYS))
    try:
        days = int(days_param)
    except (ValueError, TypeError):
        days = config.DEFAULT_DAYS

    entries = _load_all_entries(days=days if days > 0 else None)

    # Enrich entries with display metadata
    for e in entries:
        action = e.get("action", "unknown")
        e["_meta"] = ACTION_META.get(action, {"label": action, "icon": "⚪", "color": "#888", "category": "other"})
        e["_display_time"] = e["_dt"].strftime("%b %d, %Y  %I:%M:%S %p") if e["_dt"] != datetime.min else "unknown"
        e["_short_ua"] = _shorten_ua(e.get("client_ua", ""))

    return render_template_string(PAGE_TEMPLATE, entries=entries, days=days)

@app.route("/api/list")
def api_list():
    """For portal integration — returns summary stats."""
    days_param = request.args.get("days", str(config.DEFAULT_DAYS))
    try:
        days = int(days_param)
    except (ValueError, TypeError):
        days = config.DEFAULT_DAYS

    entries = _load_all_entries(days=days if days > 0 else None)

    # Count today's entries
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = sum(1 for e in entries if e["_dt"] >= today_start)

    # Recent entries (last 10) for portal summary
    recent = []
    for e in entries[:10]:
        action = e.get("action", "unknown")
        meta = ACTION_META.get(action, {"label": action, "icon": "⚪", "color": "#888", "category": "other"})
        recent.append({
            "timestamp": e.get("timestamp", ""),
            "action": action,
            "action_label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "category": meta["category"],
            "target": e.get("target", ""),
            "reason": e.get("reason", ""),
            "client_ip": e.get("client_ip", ""),
            "client_host": e.get("client_host", ""),
            "duration_min": e.get("duration_min"),
        })

    return jsonify({
        "ok": True,
        "total_entries": len(entries),
        "today_count": today_count,
        "recent": recent,
    })

if __name__ == "__main__":
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
