# UniFi Admin Portal

A unified web dashboard for the Camera Privacy Toggle and Door Lock Toggle
tools. Runs as a thin proxy layer on port 8080, routing to the independent
backend services on ports 5000 (cameras) and 5001 (doors).

## Quick Start

```bash
cd /opt/unifi-admin-portal
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
# → http://your-server:8080
```

## Prerequisites

- Camera Privacy Toggle running on port 5000 with `/api/list` endpoint
- Door Lock Toggle running on port 5001 with `/api/list` endpoint
- Both backends must have the `/api/list` patch applied (see BACKEND_PATCHES.md)

## Architecture

The portal does NOT talk to the UniFi controllers directly. It proxies
all requests through the two backend Flask apps, keeping the separation
of concerns clean. If one backend is down, the other tab still works.
