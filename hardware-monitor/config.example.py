# =============================================================================
# UniFi Hardware Monitor — Configuration
# =============================================================================

# ── Protect Controller (UNVR Pro) — cameras + NVR status ──
PROTECT_HOST = "protect.example.local"
PROTECT_USERNAME = "unifi-admin"
PROTECT_PASSWORD = "changeme"
PROTECT_API_BASE = "/proxy/protect/api"
PROTECT_VERIFY_SSL = False

# ── Access Controller (same UNVR Pro) — door hub status ──
ACCESS_HOST = "access.example.local"
ACCESS_PORT = 12445
ACCESS_TOKEN = "your-token-here"
ACCESS_VERIFY_SSL = False

# ── Network Controller (Cloud Key Gen2+) — APs, switches, Cloud Key ──
NETWORK_HOST = "network.example.local"
NETWORK_USERNAME = "unifi-admin"
NETWORK_PASSWORD = "changeme"
NETWORK_VERIFY_SSL = False

# Device names to exclude from the dashboard and alerts (exact match, case-insensitive).
EXCLUDED_DEVICES = []

# ── Email Alerts (Gmail) ──
SMTP_ENABLED = False                   # Set True once app password is configured
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "your.email@gmail.com"
SMTP_PASSWORD = ""
ALERT_FROM = "your.email@gmail.com"
ALERT_TO = ["alerts@example.com"]     # Can be multiple recipients
ALERT_SUBJECT_PREFIX = "[UniFi Monitor]"

# ── Alert Behavior ──
# Cooldown in seconds — don't re-send alert for same device within this window
ALERT_COOLDOWN = 3600                   # 1 hour

# ── Polling ──
POLL_INTERVAL = 120                     # Seconds between checks (for background thread)

# ── Flask ──
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5002
FLASK_DEBUG = False
