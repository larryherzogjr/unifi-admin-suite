# =============================================================================
# UniFi Access Door Lock Toggle — Configuration
# =============================================================================

# Controller connection
ACCESS_HOST = "protect.se-test.org"    # IP or hostname of your UNVR / UDM
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
        "Door Access Hub",
]

# Retry behavior for API calls
MAX_RETRIES = 3
RETRY_DELAY = 2                         # Seconds between retries
REQUEST_TIMEOUT = 10                    # Seconds
