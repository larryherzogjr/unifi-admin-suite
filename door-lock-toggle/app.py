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

import hmac
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from datetime import timedelta
from functools import wraps

from flask import Flask, g, jsonify, render_template_string, request

import config
import access_api
import audit_helper
from state_store import DoorStateStore, to_iso, utc_now

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("app")
app = Flask(__name__)
audit_helper.init(
    "/var/log/unifi-access-audit.log",
    unifi_network=getattr(config, "UNIFI_NETWORK", None),
)

# ── Durable state and synchronization ──
_default_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "door_state.db")
state_store = DoorStateStore(getattr(config, "STATE_DB_PATH", _default_db_path))

BUTTON_UNLOCK_MINUTES = int(getattr(config, "BUTTON_UNLOCK_MINUTES", 180))
DOOR_CACHE_INTERVAL = float(getattr(config, "DOOR_CACHE_INTERVAL", 5))
DOOR_CACHE_MAX_AGE = float(getattr(config, "DOOR_CACHE_MAX_AGE", 30))
DEADLINE_SWEEP_INTERVAL = float(getattr(config, "DEADLINE_SWEEP_INTERVAL", 15))
BUTTON_REQUEST_TTL_HOURS = int(getattr(config, "BUTTON_REQUEST_TTL_HOURS", 24))
DOOR_CONFIRM_ATTEMPTS = int(getattr(config, "DOOR_CONFIRM_ATTEMPTS", 3))
DOOR_CONFIRM_DELAY = float(getattr(config, "DOOR_CONFIRM_DELAY", 0.25))

if not 1 <= BUTTON_UNLOCK_MINUTES <= 480:
    raise ValueError("BUTTON_UNLOCK_MINUTES must be between 1 and 480")

_door_locks = defaultdict(threading.Lock)
_door_locks_guard = threading.Lock()
_door_cache = {}
_door_cache_refreshed_at = None
_door_cache_error = None
_door_cache_lock = threading.Lock()
_workers_lock = threading.Lock()
_workers_started = False
_workers_stop = threading.Event()


class DoorNotFoundError(LookupError):
    pass


class DoorConfirmationError(RuntimeError):
    pass


def _get_door_lock(door_id):
    with _door_locks_guard:
        return _door_locks[door_id]


def _replace_door_cache(doors, error=None):
    global _door_cache, _door_cache_refreshed_at, _door_cache_error
    with _door_cache_lock:
        if doors is not None:
            _door_cache = {door["id"]: dict(door) for door in doors}
            _door_cache_refreshed_at = utc_now()
        _door_cache_error = error


def _fetch_live_doors():
    doors = [access_api.door_summary(door) for door in access_api.list_doors()]
    _replace_door_cache(doors, error=None)
    return doors


def _find_live_door(door_id):
    for door in _fetch_live_doors():
        if door["id"] == door_id:
            return door
    raise DoorNotFoundError(f"unknown door: {door_id}")


def _cached_door(door_id):
    with _door_cache_lock:
        door = dict(_door_cache[door_id]) if door_id in _door_cache else None
        refreshed_at = _door_cache_refreshed_at
        error = _door_cache_error
    if refreshed_at is None:
        return door, None, error
    return door, max(0.0, (utc_now() - refreshed_at).total_seconds()), error


def _confirm_door_state(door_id, locked):
    last_error = None
    for attempt in range(max(1, DOOR_CONFIRM_ATTEMPTS)):
        try:
            summary = _find_live_door(door_id)
            confirmed = summary["lockRule"] == ("lock" if locked else "unlock")
            if confirmed:
                return summary
            last_error = DoorConfirmationError(
                f"door {door_id} reported {summary['lockRule']!r}, expected "
                f"{'lock' if locked else 'unlock'!r}"
            )
        except Exception as exc:
            last_error = exc
        if attempt + 1 < max(1, DOOR_CONFIRM_ATTEMPTS):
            time.sleep(max(0, DOOR_CONFIRM_DELAY))
    raise DoorConfirmationError(f"UniFi did not confirm door state: {last_error}")


def _command_and_confirm(door_id, locked):
    command_error = None
    try:
        if locked:
            access_api.lock_door(door_id)
        else:
            access_api.unlock_door(door_id)
    except Exception as exc:
        command_error = exc

    try:
        summary = _confirm_door_state(door_id, locked)
    except Exception:
        if command_error is not None:
            raise command_error
        raise

    if command_error is not None:
        log.warning(
            "Door command raised %r but live state confirmed success for %s",
            command_error,
            door_id,
        )
    return summary


def _lock_and_clear_deadline(door_id):
    summary = _command_and_confirm(door_id, locked=True)
    state_store.delete_timed_unlock(door_id)
    return summary


def start_timed_unlock(door_id, door_name, minutes, source="web", request_id=None):
    unlock_at = utc_now()
    lock_at = unlock_at + timedelta(minutes=int(minutes))
    row = state_store.save_timed_unlock(
        door_id=door_id,
        door_name=door_name,
        unlock_at=unlock_at,
        lock_at=lock_at,
        duration_min=int(minutes),
        source=source,
        request_id=request_id,
    )
    try:
        _command_and_confirm(door_id, locked=False)
    except Exception:
        try:
            current = _find_live_door(door_id)
            if current["lockRule"] == "lock":
                state_store.delete_timed_unlock(door_id)
        except Exception:
            pass
        raise
    log.info("Timed unlock: %s for %d min (auto-lock at %s)", door_name, minutes, row["lock_at"])
    return row


def cancel_timer(door_id):
    return state_store.delete_timed_unlock(door_id)


def get_active_timers():
    return state_store.active_timer_views()


def _sweep_expired_unlocks(now=None):
    """Relock overdue doors; retain failed rows so the next sweep retries."""
    completed = 0
    for row in state_store.list_expired_timed_unlocks(now or utc_now()):
        door_id = row["door_id"]
        door_lock = _get_door_lock(door_id)
        if not door_lock.acquire(blocking=False):
            continue
        try:
            log.warning("Timed unlock expired for %s; enforcing lock", row["door_name"])
            summary = _command_and_confirm(door_id, locked=True)
            state_store.delete_timed_unlock(door_id)
            audit_helper.write(
                "auto_relock",
                summary["name"],
                "Timed unlock deadline reached",
                actor="system:deadline-sweeper",
            )
            completed += 1
        except Exception:
            log.exception(
                "Auto-relock failed for %s; durable deadline retained for retry",
                row["door_name"],
            )
        finally:
            door_lock.release()
    return completed


def _cache_loop():
    while not _workers_stop.wait(max(1, DOOR_CACHE_INTERVAL)):
        try:
            _fetch_live_doors()
        except Exception as exc:
            _replace_door_cache(None, error=str(exc))
            log.warning("Door cache refresh failed: %s", exc)


def _deadline_loop():
    while not _workers_stop.wait(max(1, DEADLINE_SWEEP_INTERVAL)):
        _sweep_expired_unlocks()
        state_store.prune_button_requests(
            older_than=timedelta(hours=max(1, BUTTON_REQUEST_TTL_HOURS))
        )


def start_background_workers():
    global _workers_started, _workers_stop
    with _workers_lock:
        if _workers_started:
            return
        _workers_stop = threading.Event()
        try:
            _fetch_live_doors()
        except Exception as exc:
            _replace_door_cache(None, error=str(exc))
            log.warning("Initial door cache refresh failed: %s", exc)
        _sweep_expired_unlocks()
        threading.Thread(target=_cache_loop, daemon=True, name="door-cache").start()
        threading.Thread(target=_deadline_loop, daemon=True, name="deadline-sweeper").start()
        _workers_started = True


def _configured_button_devices():
    devices = getattr(config, "BUTTON_DEVICES", {})
    return devices if isinstance(devices, dict) else {}


def _button_credentials(token):
    for device_id, settings in _configured_button_devices().items():
        if not isinstance(settings, dict):
            continue
        expected = str(settings.get("token", ""))
        if expected and hmac.compare_digest(
            token.encode("utf-8"), expected.encode("utf-8")
        ):
            configured_doors = settings.get("door_ids", [])
            if not isinstance(configured_doors, (list, tuple, set)):
                configured_doors = []
            return str(device_id), {str(value) for value in configured_doors}
    return None, set()


def require_button_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        device_id, allowed_door_ids = _button_credentials(token)
        if not device_id:
            audit_helper.write(
                "button_auth_rejected",
                request.path,
                "Missing or invalid device token",
                actor="button:unknown",
            )
            return jsonify({"error": "unauthorized"}), 401
        g.button_device_id = device_id
        g.button_allowed_door_ids = allowed_door_ids
        return view(*args, **kwargs)

    return wrapped


def _authorize_button_door(door_id):
    if door_id not in g.button_allowed_door_ids:
        audit_helper.write(
            "button_door_rejected",
            door_id or "unknown",
            "Device is not authorized for this door",
            actor=f"button:{g.button_device_id}",
        )
        return False
    return True

# ── HTML Template ──
PAGE_TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Doors · UniFi Admin Suite</title><link rel="stylesheet" href="/static/suite.css"></head><body><header class="suite-header"><div><a class="suite-brand" data-portal-link href="/">UniFi Admin Suite</a><h1>Doors</h1><p>Manage locks and temporary access.</p></div><a class="btn" data-portal-link href="/">Admin portal</a></header><main class="content"><section class="control-list" data-kind="door" data-base="/api">
<div class="freshness" role="status">Checking for updates…</div>
<div class="error-box service-error" {% if not error %}hidden{% endif %}>Door service unavailable. Check the connection and retry.</div>
<div class="section-bar"><span class="section-summary"></span><div><button data-bulk="lock-all">Lock all doors</button> <button data-refresh>Refresh</button></div></div>
<div class="list-tools"><label>Search doors<input type="search" data-search placeholder="Device name or location"></label><label>Show<select data-filter><option value="all">All doors</option><option value="attention">Unlocked</option><option value="timers">Active timers</option></select></label></div>
<div class="item-list">
{% for door in doors %}
<article class="item-card {{ 'unlocked' if door.isUnlocked else 'locked' }}" data-device="{{ door.id }}" data-name="{{ door.name }}" data-active="{{ 'false' if door.isUnlocked else 'true' }}" data-offline="false">
<div class="item-top"><div class="item-info"><h2 class="item-name">{{ door.name }}</h2><div class="state-line"><span class="badge {{ 'unlocked' if door.isUnlocked else 'locked' }}">{{ 'Unlocked' if door.isUnlocked else 'Locked' }}</span></div></div>
<div class="device-actions"><button class="primary" data-disclose aria-expanded="false">Unlock for…</button><button data-toggle>{{ 'Lock now' if door.isUnlocked else 'Unlock' }}</button></div></div>
<details class="device-details-toggle"><summary>Device details</summary><div class="item-meta">Model: {{ door.type or "Unknown" }} · Controller rule: {{ door.lockRule }}</div></details>
<div class="timed-options" hidden><form><label>Duration<select class="time-select" data-duration><option value="5">5 minutes</option><option value="15" selected>15 minutes</option><option value="30">30 minutes</option><option value="60">1 hour</option><option value="120">2 hours</option><option value="custom">Custom</option></select></label><label data-custom-label hidden>Minutes (1–480)<input class="time-select" data-custom type="number" min="1" max="480" step="1" value="15"></label><label class="reason">Reason (optional)<input class="time-select" data-reason maxlength="500" placeholder="Add context for the audit log"></label><button class="primary" type="submit">Unlock temporarily</button></form><p class="time-preview"></p></div>
<div class="timer-display" hidden><span data-countdown></span><button data-cancel>Lock now</button></div><div class="card-feedback" role="status"></div>
</article>{% endfor %}</div><div class="empty-state" hidden>No matching doors. <button data-clear>Clear filters</button></div></section></main><div id="toast" class="toast" role="status"></div><script src="/static/controls.js"></script></body></html>"""

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
    data = request.get_json(silent=True) or {}
    door_id = data.get("door_id")
    should_lock = data.get("lock", True)
    reason = data.get("reason", "")
    if not door_id: return jsonify({"error": "door_id required"}), 400
    if not isinstance(should_lock, bool):
        return jsonify({"error": "lock must be a boolean"}), 400
    try:
        with _get_door_lock(door_id):
            door = _find_live_door(door_id)
            if should_lock:
                confirmed = _lock_and_clear_deadline(door_id)
                audit_helper.write("door_lock", door["name"], reason)
            else:
                confirmed = _command_and_confirm(door_id, locked=False)
                audit_helper.write("door_unlock", door["name"], reason)
        return jsonify({"ok": True, "locked": confirmed["lockRule"] == "lock"})
    except DoorNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        log.exception("Toggle failed for %s", door_id)
        return jsonify({"error": str(exc)}), 500

@app.route("/api/timed-unlock", methods=["POST"])
def api_timed_unlock():
    data = request.get_json(silent=True) or {}
    door_id = data.get("door_id")
    minutes = data.get("minutes")
    if not door_id: return jsonify({"error": "door_id required"}), 400
    if not minutes or not isinstance(minutes, (int, float)) or minutes < 1:
        return jsonify({"error": "minutes must be a positive number"}), 400
    if minutes > 480: return jsonify({"error": "max 8 hours (480 min)"}), 400
    minutes = int(minutes)
    try:
        with _get_door_lock(door_id):
            door = _find_live_door(door_id)
            row = start_timed_unlock(door_id, door["name"], minutes, source="web")
            audit_helper.write(
                "timed_door_unlock",
                door["name"],
                data.get("reason", ""),
                duration_min=minutes,
            )
        return jsonify({
            "ok": True,
            "door_id": door_id,
            "name": door["name"],
            "minutes": minutes,
            "lock_at": row["lock_at"],
        })
    except DoorNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        log.exception("Timed unlock failed for %s", door_id)
        return jsonify({"error": str(exc)}), 500

@app.route("/api/cancel-timer", methods=["POST"])
def api_cancel_timer():
    data = request.get_json(silent=True) or {}
    door_id = data.get("door_id")
    if not door_id: return jsonify({"error": "door_id required"}), 400
    try:
        with _get_door_lock(door_id):
            entry = state_store.get_timed_unlock(door_id)
            door = _find_live_door(door_id)
            _lock_and_clear_deadline(door_id)
            door_name = entry["door_name"] if entry else door["name"]
            audit_helper.write(
                "cancel_timer_door_lock",
                door_name,
                data.get("reason", "Timer cancelled"),
            )
        return jsonify({"ok": True, "name": door_name})
    except DoorNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        log.exception("Cancel timer failed for %s", door_id)
        return jsonify({"error": str(exc)}), 500

@app.route("/api/timers")
def api_timers():
    return jsonify(get_active_timers())

@app.route("/api/lock-all", methods=["POST"])
def api_lock_all():
    try:
        doors = _fetch_live_doors()
        changed = []
        failures = []
        for door in doors:
            with _get_door_lock(door["id"]):
                try:
                    if door["isUnlocked"]:
                        changed.append(_lock_and_clear_deadline(door["id"]))
                    else:
                        state_store.delete_timed_unlock(door["id"])
                except Exception as exc:
                    failures.append({"door_id": door["id"], "error": str(exc)})
        audit_helper.write("lock_all_doors", f"{len(changed)} doors", "")
        status = 500 if failures else 200
        return jsonify({
            "ok": not failures,
            "changed": len(changed),
            "doors": changed,
            "failures": failures,
        }), status
    except Exception as exc:
        log.exception("Lock-all failed")
        return jsonify({"error": str(exc)}), 500

@app.route("/api/list")
def api_list():
    try:
        with _door_cache_lock:
            cache_ready = _door_cache_refreshed_at is not None
        if not cache_ready:
            _fetch_live_doors()
        with _door_cache_lock:
            doors = [dict(door) for door in _door_cache.values()]
        timers = get_active_timers()
        for d in doors:
            if d["id"] in timers: d["timer"] = timers[d["id"]]
        return jsonify({"ok": True, "doors": doors})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/button/v1/state")
@require_button_auth
def api_button_state():
    door_id = request.args.get("door_id", "")
    if not door_id:
        return jsonify({"error": "door_id required"}), 400
    if not _authorize_button_door(door_id):
        return jsonify({"error": "forbidden for this door"}), 403

    door, cache_age, cache_error = _cached_door(door_id)
    if cache_age is None or cache_age > DOOR_CACHE_MAX_AGE:
        return jsonify({
            "error": "door state cache is unavailable or stale",
            "cache_age_sec": None if cache_age is None else round(cache_age, 3),
            "detail": cache_error,
        }), 503
    if door is None:
        return jsonify({"error": "unknown door"}), 404
    if door["lockRule"] not in ("lock", "unlock"):
        return jsonify({"error": "UniFi reported an unknown lock state"}), 503

    timed_unlock = get_active_timers().get(door_id)
    return jsonify({
        "door_id": door_id,
        "locked": door["lockRule"] == "lock",
        "door_status": door.get("doorStatus", ""),
        "timed_unlock": timed_unlock,
        "cache_age_sec": round(cache_age, 3),
        "server_time": to_iso(utc_now()),
    })


def _existing_button_result(request_id, device_id, door_id):
    existing = state_store.get_button_request(request_id)
    if not existing:
        return None, None
    if existing["device_id"] != device_id or existing["door_id"] != door_id:
        return None, (jsonify({"error": "request_id conflicts with another request"}), 409)
    if existing["action_taken"] == "pending":
        return None, (jsonify({"error": "request is still being reconciled"}), 409)
    result = dict(existing["result"])
    result["replayed"] = True
    return result, None


@app.route("/api/button/v1/toggle", methods=["POST"])
@require_button_auth
def api_button_toggle():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body must be an object"}), 400
    door_id = data.get("door_id", "")
    request_id = data.get("request_id", "")
    requested_duration = data.get("duration_min", BUTTON_UNLOCK_MINUTES)
    if not isinstance(door_id, str) or not door_id:
        return jsonify({"error": "door_id required"}), 400
    if not _authorize_button_door(door_id):
        return jsonify({"error": "forbidden for this door"}), 403
    try:
        request_id = str(uuid.UUID(str(request_id)))
    except (ValueError, TypeError, AttributeError):
        return jsonify({"error": "request_id must be a UUID"}), 400
    if requested_duration != BUTTON_UNLOCK_MINUTES:
        return jsonify({
            "error": f"duration_min is fixed at {BUTTON_UNLOCK_MINUTES}"
        }), 400

    device_id = g.button_device_id
    replay, conflict = _existing_button_result(request_id, device_id, door_id)
    if conflict:
        return conflict
    if replay:
        return jsonify(replay)

    door_lock = _get_door_lock(door_id)
    if not door_lock.acquire(blocking=False):
        return jsonify({"error": "another operation is in flight for this door"}), 409
    try:
        replay, conflict = _existing_button_result(request_id, device_id, door_id)
        if conflict:
            return conflict
        if replay:
            return jsonify(replay)
        if not state_store.begin_button_request(request_id, device_id, door_id):
            return jsonify({"error": "request_id could not be reserved"}), 409

        door = _find_live_door(door_id)
        actor = f"button:{device_id}"
        if door["lockRule"] == "unlock":
            confirmed = _lock_and_clear_deadline(door_id)
            action_taken = "locked"
            result = {
                "door_id": door_id,
                "locked": True,
                "lock_at": None,
                "request_id": request_id,
            }
            audit_helper.write(
                "door_lock",
                confirmed["name"],
                "Physical button toggle",
                actor=actor,
            )
        elif door["lockRule"] == "lock":
            row = start_timed_unlock(
                door_id,
                door["name"],
                BUTTON_UNLOCK_MINUTES,
                source=actor,
                request_id=request_id,
            )
            action_taken = "unlocked_180"
            result = {
                "door_id": door_id,
                "locked": False,
                "lock_at": row["lock_at"],
                "request_id": request_id,
            }
            audit_helper.write(
                "timed_door_unlock",
                door["name"],
                "Physical button toggle",
                duration_min=BUTTON_UNLOCK_MINUTES,
                actor=actor,
            )
        else:
            raise DoorConfirmationError(
                f"UniFi reported unknown lock state {door['lockRule']!r}"
            )

        state_store.complete_button_request(request_id, action_taken, result)
        response = dict(result)
        response["replayed"] = False
        return jsonify(response)
    except DoorNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        log.exception("Physical button toggle failed for %s", door_id)
        return jsonify({"error": str(exc)}), 503
    finally:
        door_lock.release()

if __name__ == "__main__":
    start_background_workers()
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
