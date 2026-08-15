# =============================================================================
# UniFi Access Door Lock Toggle — Configuration
# =============================================================================

# Controller connection
ACCESS_HOST = "access.example.local"   # IP or hostname of your UNVR / UDM
ACCESS_PORT = 12445                     # UniFi Access developer API port
API_TOKEN = "your-token-here"
VERIFY_SSL = False                      # Set True only if you've installed a real cert

# Flask settings
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5001                       # Using 5001 to avoid conflict with Camera Toggle on 5000
FLASK_DEBUG = False

# Door inclusion list — only these doors appear in the web UI and cron script.
# Use exact door names as shown in UniFi Access (case-insensitive).
# Empty list = show all doors.
INCLUDED_DOORS = [
    "Main Entrance",
]

# Retry behavior for API calls
MAX_RETRIES = 3
RETRY_DELAY = 2                         # Seconds between retries
REQUEST_TIMEOUT = 10                    # Seconds

# Durable timed-unlock state shared by the Flask app and nightly safety job.
# Create this directory with owner-only access before starting the service.
STATE_DB_PATH = "/var/lib/unifi-access/door_state.db"

# Background reconciliation and cache behavior.
DOOR_CACHE_INTERVAL = 5                 # Seconds between controller status polls
DOOR_CACHE_MAX_AGE = 30                 # Button treats older state as unavailable
DEADLINE_SWEEP_INTERVAL = 15            # Seconds between overdue relock attempts
DOOR_CONFIRM_ATTEMPTS = 3
DOOR_CONFIRM_DELAY = 0.25               # Seconds between confirmation reads

# Physical button API. The duration is fixed server-side. Each device token is
# restricted to explicit UniFi door UUIDs from GET /api/list.
BUTTON_UNLOCK_MINUTES = 180
BUTTON_REQUEST_TTL_HOURS = 24
BUTTON_DEVICES = {
    # "button-main-entrance-01": {
    #     "token": "replace-with-a-long-random-token",
    #     "door_ids": ["replace-with-unifi-door-uuid"],
    # },
}

# Optional UniFi Network lookup for resolving audit-log client IPs to device
# names. Leave as None to disable, or provide a local controller account.
UNIFI_NETWORK = None
# UNIFI_NETWORK = {
#     "host": "network.example.local",
#     "username": "local-admin",
#     "password": "changeme",
#     "verify_ssl": False,
# }
