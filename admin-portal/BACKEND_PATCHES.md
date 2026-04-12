# =============================================================================
# Backend Patches — add /api/list endpoints
# =============================================================================
#
# The portal needs a JSON list endpoint on each backend.
# Add these routes to the existing backend app.py files.
#
# ── Camera backend (/opt/unifi-camera-toggle/app.py) ──
# Add this route BEFORE the "if __name__" block:
#
#   @app.route("/api/list")
#   def api_list():
#       try:
#           cameras = [protect_api.camera_summary(c) for c in protect_api.list_cameras()]
#           for cam in cameras:
#               if not cam["isOff"] and cam["id"] not in _original_modes:
#                   _original_modes[cam["id"]] = cam["recordingMode"]
#           return jsonify({"cameras": cameras})
#       except Exception as exc:
#           return jsonify({"error": str(exc), "cameras": []}), 500
#
#
# ── Door backend (/opt/unifi-access/app.py) ──
# Add this route BEFORE the "if __name__" block:
#
#   @app.route("/api/list")
#   def api_list():
#       try:
#           doors = [access_api.door_summary(d) for d in access_api.list_doors()]
#           return jsonify({"doors": doors})
#       except Exception as exc:
#           return jsonify({"error": str(exc), "doors": []}), 500
#
