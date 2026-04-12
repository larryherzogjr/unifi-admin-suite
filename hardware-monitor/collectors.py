"""
UniFi hardware data collectors.

Gathers device status from three sources:
  1. Protect API (UNVR Pro) — cameras + NVR system info
  2. Access Developer API (UNVR Pro :12445) — door access hubs
  3. Network API (Cloud Key Gen2+) — APs, switches, gateway, Cloud Key
"""

import time
import logging
import urllib3
import requests

import config

log = logging.getLogger("collectors")

# Suppress SSL warnings globally for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TIMEOUT = 12


# ═══════════════════════════════════════════════════════════════════════════
# 1. PROTECT COLLECTOR — cameras + NVR
# ═══════════════════════════════════════════════════════════════════════════

_protect_session: requests.Session | None = None


def _protect_auth() -> requests.Session:
    global _protect_session
    if _protect_session:
        return _protect_session

    sess = requests.Session()
    r = sess.post(
        f"https://{config.PROTECT_HOST}/api/auth/login",
        json={"username": config.PROTECT_USERNAME, "password": config.PROTECT_PASSWORD},
        verify=config.PROTECT_VERIFY_SSL,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    csrf = r.headers.get("X-CSRF-Token") or r.headers.get("x-csrf-token")
    if csrf:
        sess.headers["X-CSRF-Token"] = csrf
    _protect_session = sess
    return sess


def _protect_get(path: str) -> dict | list:
    global _protect_session
    for attempt in range(2):
        sess = _protect_auth()
        r = sess.get(
            f"https://{config.PROTECT_HOST}{config.PROTECT_API_BASE}{path}",
            verify=config.PROTECT_VERIFY_SSL,
            timeout=TIMEOUT,
        )
        if r.status_code == 401 and attempt == 0:
            _protect_session = None
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Protect auth failed after retry")


def collect_protect_devices() -> list[dict]:
    """Collect cameras and NVR info from Protect."""
    devices = []

    # NVR system info
    try:
        info = _protect_get("/bootstrap")
        nvr = info.get("nvr", {})
        devices.append({
            "source": "protect",
            "type": "NVR",
            "name": nvr.get("name", "UNVR Pro"),
            "model": nvr.get("type", nvr.get("model", "")),
            "mac": nvr.get("mac", ""),
            "ip": config.PROTECT_HOST,
            "status": "online",
            "firmware": nvr.get("firmwareVersion", ""),
            "uptime": _format_uptime(nvr.get("uptime", 0)),
            "uptimeSecs": nvr.get("uptime", 0),
            "cpu": nvr.get("systemInfo", {}).get("cpu", {}).get("averageLoad"),
            "memory": _calc_mem_pct(nvr.get("systemInfo", {}).get("memory", {})),
            "temperature": _get_temp(nvr.get("systemInfo", {}).get("cpu", {})),
            "storage": _calc_storage(nvr.get("systemInfo", {}).get("storage", {})),
        })

        # Cameras
        for cam in info.get("cameras", []):
            state = cam.get("state", "UNKNOWN")
            devices.append({
                "source": "protect",
                "type": "Camera",
                "name": cam.get("name", cam.get("id", "")[:8]),
                "model": cam.get("type", ""),
                "mac": cam.get("mac", ""),
                "ip": cam.get("host", ""),
                "status": "online" if state == "CONNECTED" else "offline",
                "firmware": cam.get("firmwareVersion", ""),
                "uptime": _format_uptime(cam.get("uptime", 0)),
                "uptimeSecs": cam.get("uptime", 0),
                "lastSeen": cam.get("lastSeen"),
            })
    except Exception as exc:
        log.error("Protect collection failed: %s", exc)
        devices.append({
            "source": "protect", "type": "NVR", "name": "UNVR Pro",
            "ip": config.PROTECT_HOST, "status": "unreachable",
            "error": str(exc),
        })

    return devices


# ═══════════════════════════════════════════════════════════════════════════
# 2. ACCESS COLLECTOR — door hubs
# ═══════════════════════════════════════════════════════════════════════════

def collect_access_devices() -> list[dict]:
    """Collect door access hub info from the Access developer API."""
    devices = []
    try:
        r = requests.get(
            f"https://{config.ACCESS_HOST}:{config.ACCESS_PORT}/api/v1/developer/doors",
            headers={
                "Authorization": f"Bearer {config.ACCESS_TOKEN}",
                "Accept": "application/json",
            },
            verify=config.ACCESS_VERIFY_SSL,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        doors = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(doors, list):
            doors = [doors]

        # Access API doors represent hubs; deduplicate by full_name
        seen_hubs = set()
        for door in doors:
            hub_name = door.get("full_name", door.get("name", "Access Hub"))
            if hub_name in seen_hubs:
                continue
            seen_hubs.add(hub_name)
            devices.append({
                "source": "access",
                "type": "Access Hub",
                "name": hub_name,
                "model": door.get("type", ""),
                "ip": f"{config.ACCESS_HOST}:{config.ACCESS_PORT}",
                "status": "online" if door.get("is_bind_hub") else "unknown",
            })
    except Exception as exc:
        log.error("Access collection failed: %s", exc)
        devices.append({
            "source": "access", "type": "Access Hub", "name": "Access Controller",
            "ip": f"{config.ACCESS_HOST}:{config.ACCESS_PORT}", "status": "unreachable",
            "error": str(exc),
        })

    return devices


# ═══════════════════════════════════════════════════════════════════════════
# 3. NETWORK COLLECTOR — APs, switches, gateway, Cloud Key
# ═══════════════════════════════════════════════════════════════════════════

_network_session: requests.Session | None = None


def _network_auth() -> requests.Session:
    global _network_session
    if _network_session:
        return _network_session

    sess = requests.Session()
    r = sess.post(
        f"https://{config.NETWORK_HOST}/api/auth/login",
        json={"username": config.NETWORK_USERNAME, "password": config.NETWORK_PASSWORD},
        verify=config.NETWORK_VERIFY_SSL,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    csrf = r.headers.get("X-CSRF-Token") or r.headers.get("x-csrf-token")
    if csrf:
        sess.headers["X-CSRF-Token"] = csrf
    _network_session = sess
    return sess


def _network_get(path: str) -> dict | list:
    global _network_session
    for attempt in range(2):
        sess = _network_auth()
        r = sess.get(
            f"https://{config.NETWORK_HOST}{path}",
            verify=config.NETWORK_VERIFY_SSL,
            timeout=TIMEOUT,
        )
        if r.status_code == 401 and attempt == 0:
            _network_session = None
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Network auth failed after retry")


def collect_network_devices() -> list[dict]:
    """Collect APs, switches, and gateway from the Network controller."""
    devices = []
    try:
        # Get the default site's devices
        data = _network_get("/proxy/network/api/s/default/stat/device")
        device_list = data.get("data", []) if isinstance(data, dict) else data

        for dev in device_list:
            dev_type = dev.get("type", "unknown")
            state = dev.get("state", 0)
            # state: 1 = connected, others = offline/adopting/etc.

            type_label = {
                "uap": "Access Point",
                "usw": "Switch",
                "ugw": "Gateway",
                "uck": "Cloud Key",
            }.get(dev_type, dev_type.upper())

            d = {
                "source": "network",
                "type": type_label,
                "name": dev.get("name", dev.get("model", dev_type)),
                "model": dev.get("model", ""),
                "mac": dev.get("mac", ""),
                "ip": dev.get("ip", ""),
                "status": "online" if state == 1 else "offline",
                "firmware": dev.get("version", ""),
                "uptime": _format_uptime(dev.get("uptime", 0)),
                "uptimeSecs": dev.get("uptime", 0),
                "lastSeen": dev.get("last_seen"),
            }

            # System stats (CPU, memory, temp) — available on most devices
            sys_stats = dev.get("system-stats", {})
            if sys_stats:
                cpu = sys_stats.get("cpu")
                mem = sys_stats.get("mem")
                temp = sys_stats.get("temps", {})
                if cpu is not None:
                    try:
                        d["cpu"] = float(cpu)
                    except (ValueError, TypeError):
                        pass
                if mem is not None:
                    try:
                        d["memory"] = float(mem)
                    except (ValueError, TypeError):
                        pass
                # Temperature — varies by device
                if temp:
                    board_temp = temp.get("Board (CPU)", temp.get("CPU", None))
                    if board_temp is not None:
                        try:
                            d["temperature"] = float(board_temp)
                        except (ValueError, TypeError):
                            pass
                elif "general_temperature" in dev:
                    try:
                        d["temperature"] = float(dev["general_temperature"])
                    except (ValueError, TypeError):
                        pass

            devices.append(d)

    except Exception as exc:
        log.error("Network collection failed: %s", exc)
        devices.append({
            "source": "network", "type": "Cloud Key", "name": "Cloud Key Gen2+",
            "ip": config.NETWORK_HOST, "status": "unreachable",
            "error": str(exc),
        })

    return devices


# ═══════════════════════════════════════════════════════════════════════════
# COMBINED COLLECTION
# ═══════════════════════════════════════════════════════════════════════════

def collect_all() -> dict:
    """Run all collectors and return a unified snapshot."""
    start = time.time()

    protect = collect_protect_devices()
    access = collect_access_devices()
    network = collect_network_devices()

    all_devices = protect + access + network

    # Apply exclusion filter
    excluded = {n.lower() for n in getattr(config, "EXCLUDED_DEVICES", [])}
    if excluded:
        all_devices = [d for d in all_devices if (d.get("name") or "").lower() not in excluded]
    elapsed = round(time.time() - start, 2)

    online = sum(1 for d in all_devices if d.get("status") == "online")
    offline = sum(1 for d in all_devices if d.get("status") in ("offline", "unreachable"))

    return {
        "timestamp": time.time(),
        "elapsed": elapsed,
        "total": len(all_devices),
        "online": online,
        "offline": offline,
        "devices": all_devices,
    }


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _format_uptime(seconds) -> str:
    if not seconds:
        return ""
    try:
        s = int(seconds)
    except (ValueError, TypeError):
        return ""
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    elif hours > 0:
        return f"{hours}h {mins}m"
    else:
        return f"{mins}m"


def _calc_mem_pct(mem: dict) -> float | None:
    total = mem.get("total")
    available = mem.get("available")
    if total and available:
        try:
            return round((1 - available / total) * 100, 1)
        except (ValueError, TypeError, ZeroDivisionError):
            pass
    return None


def _get_temp(cpu: dict) -> float | None:
    temp = cpu.get("temperature")
    if temp is not None:
        try:
            return float(temp)
        except (ValueError, TypeError):
            pass
    return None


def _calc_storage(storage: dict) -> dict | None:
    """Return storage summary for NVR."""
    devices = storage.get("devices", [])
    if not devices:
        return None
    total = sum(d.get("size", 0) for d in devices)
    available = sum(d.get("available", 0) for d in devices if "available" in d)
    if total > 0:
        used_pct = round((1 - available / total) * 100, 1) if available else None
        return {
            "totalGB": round(total / (1024**3), 1),
            "usedPct": used_pct,
        }
    return None
