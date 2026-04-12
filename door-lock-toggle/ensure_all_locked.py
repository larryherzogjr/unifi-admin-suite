#!/usr/bin/env python3
"""
Nightly safety net — ensure every managed UniFi Access door is locked.

This is the Python equivalent of the original lock_now.sh bash script,
with the addition of door discovery via the API (rather than hardcoded
UUIDs) and inclusion-list filtering from config.py.

Usage:
    python ensure_all_locked.py            # Run once
    python ensure_all_locked.py --dry-run  # Report what would change without touching anything

Cron example (every night at 11 PM):
    0 23 * * * /opt/unifi-access/.venv/bin/python3 /opt/unifi-access/ensure_all_locked.py >> /var/log/unifi-access-ensure.log 2>&1
"""

import sys
import os
import logging
import argparse
from datetime import datetime

# Ensure the script can find sibling modules regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import access_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ensure_all_locked")


def main():
    parser = argparse.ArgumentParser(description="Ensure all Access doors are locked.")
    parser.add_argument("--dry-run", action="store_true", help="Report only, don't change anything.")
    args = parser.parse_args()

    log.info("=== Door ensure-all-locked — %s ===", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Controller: %s:%d", config.ACCESS_HOST, config.ACCESS_PORT)

    try:
        doors = access_api.list_doors()
    except Exception:
        log.exception("Failed to connect to Access controller.")
        sys.exit(1)

    needs_fix = []

    for door in doors:
        summary = access_api.door_summary(door)
        name = summary["name"]

        if summary["isUnlocked"]:
            needs_fix.append(summary)
            log.warning("  NEEDS FIX: %-30s  rule=%s", name, summary["lockRule"])
        else:
            log.info("  OK:        %-30s  rule=%s", name, summary["lockRule"])

    if not needs_fix:
        log.info("All %d door(s) are locked normally. Nothing to do.", len(doors))
        return

    if args.dry_run:
        log.info("DRY RUN — %d door(s) would be re-locked. Exiting without changes.", len(needs_fix))
        return

    fixed = 0
    for door in needs_fix:
        try:
            access_api.lock_door(door["id"])
            log.info("  FIXED: %s → locked", door["name"])
            fixed += 1
        except Exception:
            log.exception("  FAILED to lock: %s", door["name"])

    log.info("Done. Fixed %d / %d door(s).", fixed, len(needs_fix))

    if fixed < len(needs_fix):
        sys.exit(1)  # Signal partial failure to cron


if __name__ == "__main__":
    main()
