"""
UniFi Access developer API client.

Handles door listing, lock/unlock operations, and status checking via the
official developer API on port 12445 with Bearer token authentication.
"""

import time
import logging
import urllib3
import requests

import config

# Suppress InsecureRequestWarning when VERIFY_SSL is False
if not config.VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger("access_api")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _base_url() -> str:
    return f"https://{config.ACCESS_HOST}:{config.ACCESS_PORT}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _api(method: str, path: str, retries: int | None = None, **kwargs) -> requests.Response:
    """
    Make an authenticated API call with retry logic.
    Retries on transient failures (timeouts, 5xx).  Does not retry on
    4xx client errors (auth, not found, etc.).
    """
    max_attempts = retries if retries is not None else config.MAX_RETRIES
    url = f"{_base_url()}{path}"
    last_exc = None

    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.request(
                method,
                url,
                headers=_headers(),
                verify=config.VERIFY_SSL,
                timeout=config.REQUEST_TIMEOUT,
                **kwargs,
            )
            # Don't retry client errors
            if 400 <= r.status_code < 500:
                return r
            # Don't retry success
            if r.status_code < 300:
                return r
            # Server error — retry
            log.warning(
                "Server error %d on %s %s (attempt %d/%d)",
                r.status_code, method, path, attempt, max_attempts,
            )
        except requests.RequestException as exc:
            log.warning(
                "Request failed for %s %s (attempt %d/%d): %s",
                method, path, attempt, max_attempts, exc,
            )
            last_exc = exc

        if attempt < max_attempts:
            time.sleep(config.RETRY_DELAY)

    # If we exhausted retries on exceptions, raise the last one
    if last_exc:
        raise last_exc
    return r  # Return the last server-error response


# ---------------------------------------------------------------------------
# Door operations
# ---------------------------------------------------------------------------

def list_doors() -> list[dict]:
    """
    Return the list of door objects from the Access developer API.
    Filters by INCLUDED_DOORS if configured.
    """
    r = _api("GET", "/api/v1/developer/doors")
    r.raise_for_status()
    data = r.json()

    # The API wraps results in a "data" key
    doors = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(doors, list):
        doors = [doors]

    # Sort alphabetically by name
    doors.sort(key=lambda d: (d.get("name") or "").lower())

    # Apply inclusion filter
    included = {n.lower() for n in getattr(config, "INCLUDED_DOORS", [])}
    if included:
        doors = [d for d in doors if (d.get("name") or "").lower() in included]

    return doors


def door_summary(door: dict) -> dict:
    """Distill a door object down to the fields the UI cares about."""
    lock_status = door.get("door_lock_relay_status", "unknown")

    # The API reports "unlock" when open, "lock" when locked
    is_unlocked = lock_status == "unlock"

    return {
        "id": door.get("id", ""),
        "name": door.get("name", "Unknown Door"),
        "type": door.get("type", ""),
        "lockRule": lock_status,
        "isUnlocked": is_unlocked,
        "doorStatus": door.get("door_position_status", ""),
    }

def lock_door(door_id: str) -> requests.Response:
    """
    Lock a door by setting its lock rule to 'lock_now'.
    This immediately engages the lock and returns the door to its
    normal access-policy-controlled state.
    """
    payload = {"type": "lock_now"}
    r = _api("PUT", f"/api/v1/developer/doors/{door_id}/lock_rule", json=payload)
    r.raise_for_status()
    log.info("Locked door %s", door_id)
    return r


def unlock_door(door_id: str) -> requests.Response:
    """
    Unlock a door by setting its lock rule to 'keep_open'.
    The door remains unlocked until explicitly locked again.
    """
    payload = {"type": "keep_unlock"}
    r = _api("PUT", f"/api/v1/developer/doors/{door_id}/lock_rule", json=payload)
    r.raise_for_status()
    log.info("Unlocked door %s (keep_open)", door_id)
    return r

def ensure_all_doors_locked() -> list[dict]:
    """
    Safety-net function: iterate every managed door and lock any that
    are in an unlocked state.  Returns a list of doors that were re-locked.
    """
    changed = []
    for door in list_doors():
        summary = door_summary(door)
        if summary["isUnlocked"]:
            try:
                lock_door(summary["id"])
                summary["lockRule"] = "lock"
                summary["isUnlocked"] = False
                changed.append(summary)
                log.info("Re-locked door: %s (%s)", summary["name"], summary["id"])
            except Exception:
                log.exception("Failed to re-lock door: %s (%s)", summary["name"], summary["id"])
    return changed
