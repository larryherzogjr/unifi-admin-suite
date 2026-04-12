# =============================================================================
# UniFi Protect Camera Toggle — Configuration
# =============================================================================

# Controller connection
PROTECT_HOST = "protect.se-test.org"   # IP or hostname of your UDM Pro / UNVR / Cloud Key
PROTECT_USERNAME = "local-admin"
PROTECT_PASSWORD = "changeme"
VERIFY_SSL = False                      # Set True only if you've installed a real cert

# API base path — set to None for auto-detection, or override:
#   UDM Pro / UDM SE:       "/proxy/protect/api"
#   UNVR / Cloud Key Gen2+: "/api"  (older firmware may use "/protect/api")
API_BASE = "/proxy/protect/api"

# Flask settings
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
FLASK_DEBUG = False                     # Leave False in production

# Default recording mode to restore when turning cameras back ON.
# Common values: "always", "motion", "smartDetect"
# If a camera was toggled off through this tool, the original mode is
# remembered in-memory.  This fallback is used by the cron script or
# after a restart when that memory is lost.
DEFAULT_RECORDING_MODE = "always"

# Camera groups — each key becomes a URL path.
#   http://<ip>:5000/         → shows the "default" group
#   http://<ip>:5000/bob      → shows only Bob's cameras
#   http://<ip>:5000/alice    → shows only Alice's cameras
#
# Camera names are matched case-insensitively.
# The "default" group is used when no path is specified.
# If a group's list is empty [], all cameras are shown for that group.
#
# The cron safety net (ensure_all_on.py) operates on ALL cameras across
# ALL groups — it is not filtered by group.
CAMERA_GROUPS = {
    "default": [
        "Assoc. Pastor",
        "Dennis Norby",
        "Nursery",
        "Sarah Meester",
        "Youth Room",
    ],
    "dennis": [
        "Dennis Norby",
    ]
}
