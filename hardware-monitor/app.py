"""
UniFi Hardware Monitor — Flask web dashboard + background poller.

Run:  python app.py
Then visit http://your-server:5002
"""

import time
import logging
import threading
from flask import Flask, render_template_string, jsonify

import config
import collectors
import alerter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("monitor")

app = Flask(__name__)

# Cached snapshot from background poller
_snapshot: dict | None = None
_snapshot_lock = threading.Lock()


# -------------------------------------------------------------------------
# Background poller
# -------------------------------------------------------------------------

def _poll_loop():
    global _snapshot
    while True:
        try:
            data = collectors.collect_all()
            with _snapshot_lock:
                _snapshot = data
            alerter.check_and_alert(data)
            log.info(
                "Poll complete: %d devices (%d online, %d offline) in %.1fs",
                data["total"], data["online"], data["offline"], data["elapsed"],
            )
        except Exception:
            log.exception("Poll error")
        time.sleep(config.POLL_INTERVAL)


_poll_thread = threading.Thread(target=_poll_loop, daemon=True)


# -------------------------------------------------------------------------
# HTML template
# -------------------------------------------------------------------------

PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hardware Monitor</title>
<style>
  :root {
    --bg:      #0b0d10;
    --surface: #14171c;
    --card:    #1a1d23;
    --border:  #2a2d35;
    --text:    #e0e0e0;
    --muted:   #888;
    --accent:  #3b82f6;
    --danger:  #ef4444;
    --success: #22c55e;
    --warn:    #f59e0b;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); min-height: 100vh; padding: 1.5rem;
  }
  .container { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 1.3rem; font-weight: 700; margin-bottom: .2rem; }
  h1 span { color: var(--accent); }
  .subtitle { color: var(--muted); font-size: .8rem; margin-bottom: 1.2rem; }

  /* Summary bar */
  .summary {
    display: flex; gap: 1rem; margin-bottom: 1.2rem; flex-wrap: wrap;
  }
  .stat-card {
    background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: .7rem 1.2rem; flex: 1; min-width: 120px; text-align: center;
  }
  .stat-value { font-size: 1.6rem; font-weight: 700; }
  .stat-label { font-size: .7rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  .stat-value.ok { color: var(--success); }
  .stat-value.bad { color: var(--danger); }
  .stat-value.total { color: var(--accent); }

  /* Filter tabs */
  .filters {
    display: flex; gap: .4rem; margin-bottom: 1rem; flex-wrap: wrap;
  }
  .filter-btn {
    padding: .35rem .8rem; border: 1px solid var(--border); border-radius: 5px;
    background: var(--card); color: var(--muted); font-size: .75rem; cursor: pointer;
    transition: all .15s;
  }
  .filter-btn:hover { color: var(--text); border-color: var(--muted); }
  .filter-btn.active { color: var(--accent); border-color: var(--accent); background: rgba(59,130,246,.08); }

  /* Device grid */
  .device-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: .6rem;
  }
  .device-card {
    background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: .8rem 1rem; transition: border-color .2s;
  }
  .device-card.online  { border-left: 3px solid var(--success); }
  .device-card.offline { border-left: 3px solid var(--danger); }
  .device-card.unreachable { border-left: 3px solid var(--danger); }
  .device-card.unknown { border-left: 3px solid var(--muted); }

  .device-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: .4rem; }
  .device-name { font-weight: 600; font-size: .85rem; }
  .device-type { font-size: .65rem; color: var(--muted); }

  .status-dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    margin-right: .3rem; vertical-align: middle;
  }
  .status-dot.online { background: var(--success); }
  .status-dot.offline { background: var(--danger); animation: pulse 1.5s infinite; }
  .status-dot.unreachable { background: var(--danger); animation: pulse 1.5s infinite; }
  .status-dot.unknown { background: var(--muted); }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: .4; }
  }

  .device-details { font-size: .72rem; color: var(--muted); line-height: 1.6; }
  .device-details .label { display: inline-block; min-width: 70px; color: #666; }
  .device-details .val { color: var(--text); }
  .device-details .warn { color: var(--warn); }
  .device-details .bad { color: var(--danger); }

  .bar-bg {
    display: inline-block; width: 60px; height: 6px; background: var(--border);
    border-radius: 3px; vertical-align: middle; margin-left: .3rem; overflow: hidden;
  }
  .bar-fill { height: 100%; border-radius: 3px; transition: width .3s; }
  .bar-fill.ok { background: var(--success); }
  .bar-fill.warn { background: var(--warn); }
  .bar-fill.bad { background: var(--danger); }

  .refresh-bar {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 1rem;
  }
  .btn {
    padding: .4rem .8rem; border: 1px solid var(--border); border-radius: 5px;
    background: var(--card); color: var(--text); font-size: .78rem; cursor: pointer;
  }
  .btn:hover { background: #252830; }

  .last-updated { font-size: .7rem; color: var(--muted); }
  .error-msg { font-size: .72rem; color: var(--danger); margin-top: .2rem; }

  .alert-status {
    font-size: .7rem; color: var(--muted); padding: .5rem 0;
    border-top: 1px solid var(--border); margin-top: 1rem;
  }
</style>
</head>
<body>
<div class="container">
  <h1><span>Grace Free</span> Unifi Hardware Monitor</h1>
  <p class="subtitle">Real-time device health across Protect, Access, and Network</p>

  <div class="summary" id="summary"></div>
  <div class="refresh-bar">
    <div class="filters" id="filters"></div>
    <div>
      <span class="last-updated" id="lastUpdated"></span>
      <button class="btn" onclick="refresh()" style="margin-left:.5rem">Refresh</button>
    </div>
  </div>
  <div class="device-grid" id="grid"></div>
  <div class="alert-status" id="alertStatus"></div>
</div>

<script>
let allDevices = [];
let activeFilter = 'all';

function barClass(pct) {
  if (pct >= 90) return 'bad';
  if (pct >= 70) return 'warn';
  return 'ok';
}

function renderSummary(data) {
  document.getElementById('summary').innerHTML = `
    <div class="stat-card"><div class="stat-value total">${data.total}</div><div class="stat-label">Total</div></div>
    <div class="stat-card"><div class="stat-value ok">${data.online}</div><div class="stat-label">Online</div></div>
    <div class="stat-card"><div class="stat-value ${data.offline > 0 ? 'bad' : 'ok'}">${data.offline}</div><div class="stat-label">Offline</div></div>
  `;
}

function renderFilters() {
  const types = ['all', ...new Set(allDevices.map(d => d.type))];
  document.getElementById('filters').innerHTML = types.map(t =>
    `<button class="filter-btn ${activeFilter === t ? 'active' : ''}" onclick="setFilter('${t}')">${t === 'all' ? 'All' : t}</button>`
  ).join('');
}

function setFilter(f) {
  activeFilter = f;
  renderFilters();
  renderGrid();
}

function renderGrid() {
  const filtered = activeFilter === 'all' ? allDevices : allDevices.filter(d => d.type === activeFilter);
  // Sort: offline first, then by name
  filtered.sort((a,b) => {
    if (a.status !== b.status) {
      if (a.status === 'offline' || a.status === 'unreachable') return -1;
      if (b.status === 'offline' || b.status === 'unreachable') return 1;
    }
    return (a.name || '').localeCompare(b.name || '');
  });

  document.getElementById('grid').innerHTML = filtered.map(d => {
    let details = '';
    if (d.ip) details += `<div><span class="label">IP</span> <span class="val">${d.ip}</span></div>`;
    if (d.firmware) details += `<div><span class="label">Firmware</span> <span class="val">${d.firmware}</span></div>`;
    if (d.uptime) details += `<div><span class="label">Uptime</span> <span class="val">${d.uptime}</span></div>`;
    if (d.mac) details += `<div><span class="label">MAC</span> <span class="val">${d.mac}</span></div>`;
    if (d.cpu != null) {
      const cls = barClass(d.cpu);
      details += `<div><span class="label">CPU</span> <span class="val ${cls === 'bad' ? 'bad' : ''}">${d.cpu.toFixed(0)}%</span><span class="bar-bg"><span class="bar-fill ${cls}" style="width:${Math.min(d.cpu,100)}%"></span></span></div>`;
    }
    if (d.memory != null) {
      const cls = barClass(d.memory);
      details += `<div><span class="label">Memory</span> <span class="val ${cls === 'bad' ? 'bad' : ''}">${d.memory.toFixed(0)}%</span><span class="bar-bg"><span class="bar-fill ${cls}" style="width:${Math.min(d.memory,100)}%"></span></span></div>`;
    }
    if (d.temperature != null) {
      const cls = d.temperature >= 80 ? 'bad' : d.temperature >= 65 ? 'warn' : '';
      details += `<div><span class="label">Temp</span> <span class="val ${cls}">${d.temperature.toFixed(0)}\u00B0C</span></div>`;
    }
    if (d.storage) {
      let storStr = `${d.storage.totalGB} GB`;
      if (d.storage.usedPct != null) storStr += ` (${d.storage.usedPct}% used)`;
      details += `<div><span class="label">Storage</span> <span class="val">${storStr}</span></div>`;
    }
    if (d.error) details += `<div class="error-msg">${d.error}</div>`;

    return `<div class="device-card ${d.status}">
      <div class="device-header">
        <div>
          <span class="status-dot ${d.status}"></span>
          <span class="device-name">${d.name}</span>
        </div>
        <span class="device-type">${d.type}${d.model ? ' \u00B7 ' + d.model : ''}</span>
      </div>
      <div class="device-details">${details}</div>
    </div>`;
  }).join('');
}

async function refresh() {
  try {
    const r = await fetch('/api/snapshot');
    const data = await r.json();
    allDevices = data.devices || [];
    renderSummary(data);
    renderFilters();
    renderGrid();

    const ts = data.timestamp ? new Date(data.timestamp * 1000).toLocaleTimeString() : 'N/A';
    document.getElementById('lastUpdated').textContent = `Updated: ${ts} (${data.elapsed}s)`;

    // Alert status
    const ar = await fetch('/api/alert-status');
    const as_ = await ar.json();
    document.getElementById('alertStatus').textContent =
      as_.enabled ? `Email alerts: ON \u00B7 Tracking ${as_.tracked_devices} devices \u00B7 Cooldown: ${Math.round(as_.cooldown_seconds/60)}min`
                  : 'Email alerts: OFF \u2014 configure SMTP in config.py to enable';
  } catch(e) {
    document.getElementById('lastUpdated').textContent = 'Error: ' + e.message;
  }
}

// Initial load + auto-refresh
refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>
"""


# -------------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/api/snapshot")
def api_snapshot():
    with _snapshot_lock:
        if _snapshot:
            return jsonify(_snapshot)
    # If no snapshot yet, do a live collection
    data = collectors.collect_all()
    return jsonify(data)


@app.route("/api/list")
def api_list():
    """For portal integration."""
    with _snapshot_lock:
        if _snapshot:
            return jsonify({"devices": _snapshot["devices"], "summary": {
                "total": _snapshot["total"],
                "online": _snapshot["online"],
                "offline": _snapshot["offline"],
            }})
    data = collectors.collect_all()
    return jsonify({"devices": data["devices"], "summary": {
        "total": data["total"],
        "online": data["online"],
        "offline": data["offline"],
    }})


@app.route("/api/alert-status")
def api_alert_status():
    return jsonify(alerter.get_alert_status())


# -------------------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------------------

if __name__ == "__main__":
    _poll_thread.start()
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
