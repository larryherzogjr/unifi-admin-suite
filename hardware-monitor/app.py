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
<link rel="stylesheet" href="/static/suite.css">
</head>
<body><header class="suite-header"><div><a class="suite-brand" data-portal-link href="/">UniFi Admin Suite</a><h1>Hardware Monitor</h1><p>Device health across Protect, Access, and Network</p></div><a class="btn" data-portal-link href="/">Admin portal</a></header><main class="container">
<div class="summary"><button class="stat-card" data-status="all" aria-pressed="true"><span class="stat-value total" id="totalCount">—</span><br><span class="stat-label">All devices</span></button><button class="stat-card" data-status="online" aria-pressed="false"><span class="stat-value ok" id="onlineCount">—</span><br><span class="stat-label">Online</span></button><button class="stat-card" data-status="offline" aria-pressed="false"><span class="stat-value bad" id="offlineCount">—</span><br><span class="stat-label">Offline</span></button></div>
<div class="list-tools"><label>Search devices<input type="search" id="deviceSearch" placeholder="Name or IP address"></label><button id="refresh">Refresh</button></div><div class="filters" id="filters" aria-label="Device type"></div><p class="freshness" id="lastUpdated" role="status">Loading device health…</p><div id="monitorError" class="error-box" role="alert" hidden></div><p class="stats" id="resultCount"></p><div class="device-grid" id="grid"></div><div class="empty-state" id="noDevices" hidden>No matching devices. <button id="clearDevices">Clear filters</button></div><div class="alert-status" id="alertStatus"></div></main><script src="/static/monitor.js"></script></body></html>"""


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
