#!/usr/bin/env python3
"""
Nightly safety net — ensure every managed UniFi Access door is locked unless it
has a valid durable timed-unlock deadline.

The deployed systemd timer runs this script at 7:00 PM America/Chicago:
    door-ensure-all-locked.timer

Usage:
    python ensure_all_locked.py            # Run once
    python ensure_all_locked.py --dry-run  # Report without changing state
"""

import argparse
import logging
import os
import sys

# Ensure the script can find sibling modules regardless of cwd.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import access_api
import config
from state_store import DoorStateStore, utc_now

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ensure_all_locked")


def _state_store():
    default_path = os.path.join(SCRIPT_DIR, "door_state.db")
    return DoorStateStore(getattr(config, "STATE_DB_PATH", default_path))


def _live_summary(door_id):
    for door in access_api.list_doors():
        summary = access_api.door_summary(door)
        if summary["id"] == door_id:
            return summary
    return None


def run_safety_check(dry_run=False, store=None, now=None):
    """Reconcile live locks with durable deadlines and return result counts."""
    store = store or _state_store()
    now = now or utc_now()
    doors = access_api.list_doors()
    needs_fix = []
    preserved = []

    for raw_door in doors:
        door = access_api.door_summary(raw_door)
        row = store.get_timed_unlock(door["id"])

        if not door["isUnlocked"]:
            log.info("  OK:        %-30s  rule=%s", door["name"], door["lockRule"])
            if row and not dry_run:
                store.delete_timed_unlock(door["id"])
                log.info("  CLEANED:   stale timed-unlock row for %s", door["name"])
            continue

        if store.is_valid_active_unlock(row, now):
            preserved.append(door)
            log.info(
                "  PRESERVED: %-30s  valid timed unlock until %s",
                door["name"],
                row["lock_at"],
            )
            continue

        needs_fix.append(door)
        reason = "no durable timed unlock" if row is None else "expired or invalid timed unlock"
        log.warning(
            "  NEEDS FIX: %-30s  rule=%s (%s)",
            door["name"],
            door["lockRule"],
            reason,
        )

    if dry_run:
        log.info(
            "DRY RUN — %d door(s) would be locked; %d valid timed unlock(s) preserved.",
            len(needs_fix),
            len(preserved),
        )
        return {"fixed": 0, "failed": 0, "preserved": len(preserved), "candidates": len(needs_fix)}

    fixed = 0
    failed = 0
    for door in needs_fix:
        command_error = None
        try:
            access_api.lock_door(door["id"])
        except Exception as exc:
            command_error = exc

        try:
            confirmed = _live_summary(door["id"])
            if not confirmed or confirmed["lockRule"] != "lock":
                raise RuntimeError("UniFi did not confirm locked state")
            store.delete_timed_unlock(door["id"])
            log.info("  FIXED: %s → locked", door["name"])
            fixed += 1
        except Exception:
            if command_error is not None:
                log.error("  Lock command failed for %s: %s", door["name"], command_error)
            log.exception("  FAILED to confirm lock: %s", door["name"])
            failed += 1

    log.info(
        "Done. Fixed %d, preserved %d, failed %d.",
        fixed,
        len(preserved),
        failed,
    )
    return {
        "fixed": fixed,
        "failed": failed,
        "preserved": len(preserved),
        "candidates": len(needs_fix),
    }


def main():
    parser = argparse.ArgumentParser(description="Ensure all Access doors are safely locked.")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not change state.")
    args = parser.parse_args()

    log.info("=== Door ensure-all-locked — %s ===", utc_now().isoformat(timespec="seconds"))
    log.info("Controller: %s:%d", config.ACCESS_HOST, config.ACCESS_PORT)

    try:
        result = run_safety_check(dry_run=args.dry_run)
    except Exception:
        log.exception("Safety check failed before reconciliation completed.")
        sys.exit(1)

    if result["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
