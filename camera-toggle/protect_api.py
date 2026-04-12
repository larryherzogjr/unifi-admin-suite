"""
UniFi Protect API client.

Handles authentication, camera listing, and toggling recording/privacy state
via the local controller API.  Works with UDM Pro/SE, UNVR, and Cloud Key Gen2+.
"""

import json
import logging
import urllib3
import requests

import config

# Suppress the noisy InsecureRequestWarning when VERIFY_SSL is False
if not config.VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger("protect_api")

# ---------------------------------------------------------------------------
# Session / auth
# ---------------------------------------------------------------------------

_session: requests.Session | None = None
_api_base: str | None = None


def _base_url() -> str:
    return f"https://{config.PROTECT_HOST}"


def _detect_api_base(sess: requests.Session) -> str:
    """Try the two known API base paths and return whichever responds."""
    candidates = ["/proxy/protect/api", "/api"]
    for path in candidates:
        try:
            r = sess.get(
                f"{_base_url()}{path}/cameras",
                verify=config.VERIFY_SSL,
                timeout=10,
            )
            if r.status_code in (200, 401, 403):
                log.info("Detected API base path: %s", path)
                return path
        except requests.RequestException:
            continue
    raise RuntimeError(
        f"Could not detect Protect API base on {config.PROTECT_HOST}. "
        "Try setting API_BASE explicitly in config.py."
    )


def _get_session() -> tuple[requests.Session, str]:
    """Return an authenticated session and the resolved API base path."""
    global _session, _api_base

    if _session is not None and _api_base is not None:
        return _session, _api_base

    sess = requests.Session()

    # Resolve API base
    if config.API_BASE:
        _api_base = config.API_BASE.rstrip("/")
    else:
        _api_base = _detect_api_base(sess)

    # Authenticate — the controller returns a session cookie (TOKEN).
    auth_url = f"{_base_url()}/api/auth/login"
    r = sess.post(
        auth_url,
        json={
            "username": config.PROTECT_USERNAME,
            "password": config.PROTECT_PASSWORD,
        },
        verify=config.VERIFY_SSL,
        timeout=15,
    )
    r.raise_for_status()

    # The CSRF token lives in a response header on newer firmware.
    csrf = r.headers.get("X-CSRF-Token") or r.headers.get("x-csrf-token")
    if csrf:
        sess.headers["X-CSRF-Token"] = csrf

    _session = sess
    log.info("Authenticated to Protect controller at %s", config.PROTECT_HOST)
    return _session, _api_base


def invalidate_session():
    """Force re-authentication on next call."""
    global _session, _api_base
    _session = None
    _api_base = None


def _api(method: str, path: str, **kwargs) -> requests.Response:
    """Make an authenticated API call, retrying auth once if expired."""
    for attempt in range(2):
        sess, base = _get_session()
        url = f"{_base_url()}{base}{path}"
        r = sess.request(method, url, verify=config.VERIFY_SSL, timeout=15, **kwargs)
        if r.status_code == 401 and attempt == 0:
            log.warning("Session expired — re-authenticating.")
            invalidate_session()
            continue
        return r
    raise RuntimeError("Authentication failed after retry.")


# ---------------------------------------------------------------------------
# Camera operations
# ---------------------------------------------------------------------------

def _get_group_filter(group: str | None = None) -> set[str]:
    """
    Return the set of lowercase camera names for the given group.
    Empty set means show all cameras (no filtering).
    """
    groups = getattr(config, "CAMERA_GROUPS", {})
    if group and group in groups:
        names = groups[group]
    elif "default" in groups:
        names = groups["default"]
    else:
        names = []
    return {n.lower() for n in names} if names else set()


def list_cameras(group: str | None = None) -> list[dict]:
    """
    Return the list of camera objects from Protect,
    filtered by the specified group from CAMERA_GROUPS.
    """
    r = _api("GET", "/cameras")
    r.raise_for_status()
    cameras = r.json()
    # Sort alphabetically by name for consistent UI order
    cameras.sort(key=lambda c: (c.get("name") or "").lower())
    # Filter by group inclusion list
    included = _get_group_filter(group)
    if included:
        cameras = [c for c in cameras if (c.get("name") or "").lower() in included]
    return cameras


def list_all_cameras() -> list[dict]:
    """
    Return ALL cameras with no group filtering.
    Used by the cron safety net and the /api/list endpoint.
    """
    r = _api("GET", "/cameras")
    r.raise_for_status()
    cameras = r.json()
    cameras.sort(key=lambda c: (c.get("name") or "").lower())
    return cameras


def get_camera(camera_id: str) -> dict:
    """Return a single camera object."""
    r = _api("GET", f"/cameras/{camera_id}")
    r.raise_for_status()
    return r.json()


def camera_summary(cam: dict) -> dict:
    """Distill a camera object down to the fields the UI cares about."""
    rec_mode = cam.get("recordingSettings", {}).get("mode", "unknown")
    is_off = rec_mode == "never"

    return {
        "id": cam["id"],
        "name": cam.get("name", cam["id"][:8]),
        "type": cam.get("type", "unknown"),
        "state": cam.get("state", "unknown"),           # CONNECTED / DISCONNECTED
        "recordingMode": rec_mode,
        "isOff": is_off,
        "host": cam.get("host", ""),
        "firmwareVersion": cam.get("firmwareVersion", ""),
    }


def set_camera_off(camera_id: str) -> dict:
    """
    Disable a camera: stop recording and enable a full privacy zone.
    Returns the updated camera object.
    """
    payload = {
        "recordingSettings": {"mode": "never"},
        # Full-frame privacy zone — blacks out the live view.
        # Coordinates are 0-1 normalized; this covers the entire frame.
        "privacyZones": [
            {
                "id": 0,
                "name": "Full Privacy",
                "color": "#000000",
                "points": [
                    [0, 0],
                    [1, 0],
                    [1, 1],
                    [0, 1],
                ],
            }
        ],
    }
    r = _api("PATCH", f"/cameras/{camera_id}", json=payload)
    r.raise_for_status()
    return r.json()


def set_camera_on(camera_id: str, recording_mode: str | None = None) -> dict:
    """
    Re-enable a camera: restore recording and clear privacy zones.
    If recording_mode is not supplied, falls back to config.DEFAULT_RECORDING_MODE.
    """
    mode = recording_mode or config.DEFAULT_RECORDING_MODE
    payload = {
        "recordingSettings": {"mode": mode},
        "privacyZones": [],
    }
    r = _api("PATCH", f"/cameras/{camera_id}", json=payload)
    r.raise_for_status()
    return r.json()


def ensure_all_cameras_on(recording_mode: str | None = None) -> list[dict]:
    """
    Safety-net function: iterate every camera (unfiltered) and make sure
    recording is enabled and privacy zones are cleared.  Returns a list
    of cameras that were changed.
    """
    mode = recording_mode or config.DEFAULT_RECORDING_MODE
    changed = []
    for cam in list_all_cameras():
        rec = cam.get("recordingSettings", {}).get("mode", "")
        has_privacy = bool(cam.get("privacyZones"))
        if rec == "never" or has_privacy:
            result = set_camera_on(cam["id"], mode)
            changed.append(camera_summary(result))
            log.info("Re-enabled camera: %s (%s)", cam.get("name"), cam["id"])
    return changed
