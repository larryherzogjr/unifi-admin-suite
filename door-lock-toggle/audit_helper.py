"""
Audit logging helper — writes JSON lines to a dedicated log file.

Includes best-effort device name resolution via:
  1. UniFi Network controller client list (API query, works across subnets)
  2. mDNS / Avahi (local subnet, great for Apple devices)
  3. NetBIOS / nmblookup (local subnet, Windows + some macOS)
  4. Reverse DNS
  5. Raw IP fallback

Each audit entry includes:
  timestamp, action, target, reason, duration_min,
  actor, client_ip, client_device, client_host, client_ua
"""

import json
import socket
import subprocess
import logging
import threading
import requests as http_requests
from datetime import datetime, timedelta
from flask import has_request_context, request

log = logging.getLogger("audit")

_audit_file = None

# ── UniFi Network controller config ──
_unifi_network = None  # { host, username, password, verify_ssl }
_unifi_session = None
_unifi_session_lock = threading.Lock()

# ── Device name cache ──
_device_cache = {}
_cache_lock = threading.Lock()
_CACHE_TTL = timedelta(hours=1)

# ── UniFi client list cache ──
_unifi_clients = {}  # { ip: hostname }
_unifi_clients_expires = datetime.min
_unifi_clients_lock = threading.Lock()
_UNIFI_CACHE_TTL = timedelta(minutes=5)


def init(filepath: str, unifi_network: dict = None):
    """
    Set the audit log file path and optional UniFi Network controller config.

    unifi_network = {
        "host": "10.42.42.7",
        "username": "local-admin",
        "password": "changeme",
        "verify_ssl": False,
    }
    """
    global _audit_file, _unifi_network
    _audit_file = filepath
    _unifi_network = unifi_network
    log.info("Audit log: %s", filepath)
    if _unifi_network:
        log.info("UniFi Network client lookup enabled: %s", _unifi_network["host"])


# ── UniFi Network API ──

def _unifi_login():
    """Authenticate to the UniFi Network controller and return a session."""
    global _unifi_session
    if not _unifi_network:
        return None
    try:
        sess = http_requests.Session()
        sess.verify = _unifi_network.get("verify_ssl", False)
        r = sess.post(
            f"https://{_unifi_network['host']}/api/auth/login",
            json={
                "username": _unifi_network["username"],
                "password": _unifi_network["password"],
            },
            timeout=5,
        )
        if r.status_code == 200:
            _unifi_session = sess
            return sess
        # Try legacy login path (Cloud Key)
        r = sess.post(
            f"https://{_unifi_network['host']}/api/login",
            json={
                "username": _unifi_network["username"],
                "password": _unifi_network["password"],
            },
            timeout=5,
        )
        if r.status_code == 200:
            _unifi_session = sess
            return sess
    except Exception:
        log.debug("UniFi Network login failed")
    return None


def _fetch_unifi_clients():
    """Fetch the full client list from UniFi Network controller."""
    global _unifi_clients, _unifi_clients_expires

    with _unifi_clients_lock:
        if datetime.now() < _unifi_clients_expires:
            return _unifi_clients

    if not _unifi_network:
        return {}

    with _unifi_session_lock:
        sess = _unifi_session or _unifi_login()
        if not sess:
            return {}

        try:
            # Try the proxy path (Cloud Key Gen2+)
            r = sess.get(
                f"https://{_unifi_network['host']}/proxy/network/api/s/default/stat/sta",
                timeout=8,
            )
            if r.status_code == 401:
                sess = _unifi_login()
                if not sess:
                    return {}
                r = sess.get(
                    f"https://{_unifi_network['host']}/proxy/network/api/s/default/stat/sta",
                    timeout=8,
                )
            if r.status_code == 200:
                data = r.json()
                clients = {}
                for client in data.get("data", []):
                    ip = client.get("ip")
                    if ip:
                        # Prefer 'name' (user-set alias), then 'hostname' (DHCP/auto)
                        name = client.get("name") or client.get("hostname")
                        if name:
                            clients[ip] = name
                with _unifi_clients_lock:
                    _unifi_clients = clients
                    _unifi_clients_expires = datetime.now() + _UNIFI_CACHE_TTL
                log.debug("Fetched %d clients from UniFi Network controller", len(clients))
                return clients
        except Exception:
            log.debug("UniFi client list fetch failed")

    return {}


def _resolve_unifi(ip):
    """Look up a client name from the UniFi Network controller."""
    clients = _fetch_unifi_clients()
    return clients.get(ip)


# ── Other resolution methods ──

def _run_cmd(args, timeout=3):
    """Run a subprocess with timeout, return stdout or None."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _resolve_mdns(ip):
    """Try mDNS (Bonjour/Avahi) resolution."""
    output = _run_cmd(["avahi-resolve", "-a", ip], timeout=3)
    if output:
        parts = output.split("\t")
        if len(parts) >= 2:
            name = parts[1].strip()
            if name.endswith(".local"):
                name = name[:-6]
            return name
    return None


def _resolve_netbios(ip):
    """Try NetBIOS name lookup."""
    output = _run_cmd(["nmblookup", "-A", ip], timeout=3)
    if output:
        for line in output.splitlines():
            line = line.strip()
            if "<00>" in line and "GROUP" not in line:
                name = line.split("<")[0].strip()
                if name and not name.startswith("Looking"):
                    return name
    return None


def _resolve_rdns(ip):
    """Try reverse DNS lookup."""
    try:
        hostname = socket.gethostbyaddr(ip)[0]
        if hostname and hostname != ip:
            return hostname
    except (socket.herror, socket.gaierror, OSError):
        pass
    return None


def resolve_device_name(ip):
    """
    Best-effort device name resolution.
    Tries: UniFi clients → mDNS → NetBIOS → reverse DNS → raw IP.
    Results are cached for 1 hour.
    """
    if not ip or ip in ("unknown", "127.0.0.1"):
        return "localhost" if ip == "127.0.0.1" else ip or "unknown"

    clean_ip = ip.split(",")[0].strip().split(":")[0]

    # Check cache
    with _cache_lock:
        cached = _device_cache.get(clean_ip)
        if cached and datetime.now() < cached["expires"]:
            return cached["name"]

    name = None

    # 1. UniFi Network controller client list
    if _unifi_network:
        name = _resolve_unifi(clean_ip)

    # 2. mDNS (Apple devices)
    if not name:
        name = _resolve_mdns(clean_ip)

    # 3. NetBIOS (Windows)
    if not name:
        name = _resolve_netbios(clean_ip)

    # 4. Reverse DNS
    if not name:
        name = _resolve_rdns(clean_ip)

    # 5. Raw IP fallback
    if not name:
        name = clean_ip

    # Cache
    with _cache_lock:
        _device_cache[clean_ip] = {
            "name": name,
            "expires": datetime.now() + _CACHE_TTL,
        }

    log.debug("Resolved %s -> %s", clean_ip, name)
    return name


def write(
    action: str,
    target: str,
    reason: str = "",
    duration_min: int = None,
    actor: str = None,
):
    """Write an audit entry."""
    if has_request_context():
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
        client_ua = request.headers.get(
            "X-Forwarded-User-Agent", request.headers.get("User-Agent", "unknown")
        )
        actor = actor or "web-ui"
    else:
        client_ip = "localhost"
        client_ua = "system"
        actor = actor or "system"

    client_device = resolve_device_name(client_ip)

    try:
        clean_ip = client_ip.split(",")[0].strip()
        client_host = socket.gethostbyaddr(clean_ip)[0]
    except Exception:
        client_host = client_ip

    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "target": target,
        "reason": reason or "",
        "duration_min": duration_min,
        "actor": actor,
        "client_ip": client_ip,
        "client_device": client_device,
        "client_host": client_host,
        "client_ua": client_ua,
    }

    log.info(
        "AUDIT: %s %s actor=%s by %s [%s] (%s) reason=%r",
        action,
        target,
        actor,
        client_ip,
        client_device,
        client_host,
        reason,
    )

    if _audit_file:
        try:
            with open(_audit_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            log.exception("Failed to write audit log to %s", _audit_file)
