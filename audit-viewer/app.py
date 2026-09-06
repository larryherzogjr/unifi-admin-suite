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
<title>Audit Log Viewer</title><link rel="stylesheet" href="/static/suite.css"></head><body><header class="suite-header"><div><a class="suite-brand" data-portal-link href="/">UniFi Admin Suite</a><h1>Audit Log</h1><p>Camera and door action history · Read only</p></div><a class="btn" data-portal-link href="/">Admin portal</a></header><main class="container"><div class="audit-controls"><label>Search history<input type="search" class="search-box" id="search" placeholder="Device, reason, IP, hostname or action"></label><div class="filter-group" aria-label="Category"><span>Category</span><button class="filter-btn" data-filter="all">All</button><button class="filter-btn" data-filter="camera">Cameras</button><button class="filter-btn" data-filter="door">Doors</button></div><div class="filter-group" aria-label="Time period"><span>Period</span>{% for value, label in [(1,'Today'),(7,'7 days'),(30,'30 days'),(0,'All time')] %}<button class="filter-btn {{ 'active' if days == value else '' }}" aria-pressed="{{ 'true' if days == value else 'false' }}" data-days="{{ value }}">{{ label }}</button>{% endfor %}<button id="auditRefresh">Refresh</button></div></div><div class="stats" id="stats" role="status">{{ entries | length }} entries</div>

<div class="entry-list" id="entry-list">

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
</div><div class="empty-state" id="noMatches" hidden>No matching entries in this period. <button id="clearAudit">Clear filters</button></div>
</main>

<script src="/static/audit.js"></script>
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
