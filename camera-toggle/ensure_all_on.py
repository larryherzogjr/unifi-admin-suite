#!/usr/bin/env python3
"""
Nightly safety net — ensure every UniFi Protect camera is recording and
privacy zones are cleared.

Usage:
    python ensure_all_on.py            # Run once
    python ensure_all_on.py --dry-run  # Report what would change without touching anything

Cron example (every night at 11 PM):
    0 23 * * * /usr/bin/python3 /path/to/unifi-camera-toggle/ensure_all_on.py >> /var/log/camera-ensure.log 2>&1
"""

import sys
import os
import logging
import argparse
from datetime import datetime

# Ensure the script can find sibling modules regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import protect_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ensure_all_on")


def main():
    parser = argparse.ArgumentParser(description="Ensure all Protect cameras are enabled.")
    parser.add_argument("--dry-run", action="store_true", help="Report only, don't change anything.")
    parser.add_argument("--mode", default=None, help=f"Recording mode to set (default: {config.DEFAULT_RECORDING_MODE})")
    args = parser.parse_args()

    log.info("=== Camera ensure-all-on — %s ===", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Controller: %s", config.PROTECT_HOST)

    try:
        cameras = protect_api.list_cameras()
    except Exception:
        log.exception("Failed to connect to Protect controller.")
        sys.exit(1)

    mode = args.mode or config.DEFAULT_RECORDING_MODE
    needs_fix = []

    for cam in cameras:
        rec = cam.get("recordingSettings", {}).get("mode", "")
        has_privacy = bool(cam.get("privacyZones"))
        name = cam.get("name", cam["id"][:8])

        if rec == "never" or has_privacy:
            needs_fix.append(cam)
            log.warning("  NEEDS FIX: %-30s  mode=%s  privacy_zones=%d", name, rec, len(cam.get("privacyZones", [])))
        else:
            log.info("  OK:        %-30s  mode=%s", name, rec)

    if not needs_fix:
        log.info("All %d cameras are recording normally. Nothing to do.", len(cameras))
        return

    if args.dry_run:
        log.info("DRY RUN — %d camera(s) would be re-enabled. Exiting without changes.", len(needs_fix))
        return

    fixed = 0
    for cam in needs_fix:
        name = cam.get("name", cam["id"][:8])
        try:
            protect_api.set_camera_on(cam["id"], mode)
            log.info("  FIXED: %s → mode=%s, privacy zones cleared", name, mode)
            fixed += 1
        except Exception:
            log.exception("  FAILED to fix: %s", name)

    log.info("Done. Fixed %d / %d camera(s).", fixed, len(needs_fix))

    if fixed < len(needs_fix):
        sys.exit(1)  # Signal partial failure to cron


if __name__ == "__main__":
    main()
