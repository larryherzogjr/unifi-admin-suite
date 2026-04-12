# =============================================================================
# Admin Portal Patch — Add Monitor Tab
# =============================================================================
#
# Add these changes to /opt/unifi-admin-portal/app.py and config.py
#
# ── 1. config.py — add monitor backend ──
#
#   MONITOR_BACKEND = "http://127.0.0.1:5002"
#
#
# ── 2. app.py — add data fetcher function (near the other _fetch_ functions) ──
#
#   def _fetch_monitor_data():
#       """Get device list from the monitor backend."""
#       try:
#           r = requests.get(
#               f"{config.MONITOR_BACKEND}/api/list",
#               timeout=BACKEND_TIMEOUT,
#           )
#           if r.status_code == 200:
#               data = r.json()
#               return data.get("devices", []), data.get("summary", {})
#       except Exception:
#           pass
#       return None, None
#
#
# ── 3. app.py — update the index() route to fetch monitor data ──
#
#   Add after the door data fetch block:
#
#     monitor_devices = []
#     monitor_summary = {}
#     monitor_error = None
#     mon_data, mon_summary = _fetch_monitor_data()
#     if mon_data is None:
#         monitor_error = "Cannot reach monitor service on port 5002"
#     else:
#         monitor_devices = mon_data
#         monitor_summary = mon_summary
#
#   And pass these to render_template_string:
#     monitor_devices=monitor_devices,
#     monitor_error=monitor_error,
#     monitor_summary=monitor_summary,
#
#
# ── 4. app.py — add a Monitor tab in the HTML tabs div ──
#
#   After the Doors tab div:
#
#     <div class="tab" data-panel="monitor" onclick="switchTab(this)">
#       Monitor
#       {% if monitor_summary.get('offline', 0) > 0 %}
#         <span class="count alert">{{ monitor_summary.offline }} down</span>
#       {% else %}
#         <span class="count">{{ monitor_devices | length }}</span>
#       {% endif %}
#     </div>
#
#
# ── 5. app.py — add a Monitor panel in the content div ──
#
#   After the doors panel closing div:
#
#     <!-- MONITOR PANEL -->
#     <div class="panel" id="panel-monitor">
#       {% if monitor_error %}
#         <div class="error-box">Monitor service unavailable: {{ monitor_error }}</div>
#       {% elif monitor_devices | length == 0 %}
#         <div class="empty-state">No devices found.</div>
#       {% else %}
#         <div class="section-bar">
#           <span class="section-summary">
#             {{ monitor_summary.get('total', 0) }} devices
#             &middot; {{ monitor_summary.get('online', 0) }} online
#             &middot; {{ monitor_summary.get('offline', 0) }} offline
#           </span>
#           <a href="http://{{ request.host.split(':')[0] }}:5002" target="_blank"
#              class="btn" style="text-decoration:none">Full Dashboard</a>
#         </div>
#         <div class="item-list">
#         {% for dev in monitor_devices %}
#           <div class="item-card {{ 'on' if dev.status == 'online' else 'off' }}">
#             <div class="item-info">
#               <div class="item-name">{{ dev.name }}</div>
#               <div class="item-meta">
#                 {{ dev.type }}
#                 {% if dev.model %}&middot; {{ dev.model }}{% endif %}
#                 &middot;
#                 <span class="badge {{ 'connected' if dev.status == 'online' else 'disconnected' }}">
#                   {{ dev.status | upper }}
#                 </span>
#                 {% if dev.ip %}&middot; {{ dev.ip }}{% endif %}
#                 {% if dev.firmware %}&middot; FW: {{ dev.firmware }}{% endif %}
#                 {% if dev.uptime %}&middot; Up: {{ dev.uptime }}{% endif %}
#               </div>
#             </div>
#           </div>
#         {% endfor %}
#         </div>
#       {% endif %}
#     </div>
#
#
# ── 6. Update the portal systemd service to start after the monitor ──
#
#   In /etc/systemd/system/unifi-admin-portal.service, update the After= line:
#
#   After=network-online.target camera-toggle.service door-lock-toggle.service unifi-monitor.service
#
