# Shared suite UI

Edit the canonical CSS and JavaScript in this directory, then run:

```sh
python ui/sync_assets.py
```

The script copies only the required assets into each service's `static/`
directory. These copies are committed so each Flask service remains independently
deployable. Deploy its `static/` directory together with `app.py`. There is no
frontend build or additional runtime dependency.

- `suite.css`: shared layout, colors, typography, mobile rules and focus styles.
- `controls.js`: portal tabs, camera/door actions, timers, search and refresh.
- `monitor.js`: device health, filters and snapshot freshness.
- `audit.js`: search/category state in the URL and date navigation.

The existing backend endpoints remain the source of device state. Control actions
preserve open forms, refresh server-rendered device metadata in place, and report
unverified state separately from confirmed changes. Countdown expiry does not
claim that a lock or recording change succeeded. Refresh failures retain the last
known device state and show a warning. Untimed pause/unlock and bulk commands
require an explicit confirmation in the UI.

Standalone portal links use the existing same-host port 8080 deployment model.
The portal's full dashboard and audit links retain ports 5002 and 5004.

## Verification

Run JavaScript syntax checks and the door backend's existing regression suite:

```sh
node --check ui/controls.js
node --check ui/monitor.js
node --check ui/audit.js
python -m unittest discover -s door-lock-toggle/tests
```

Use simulated devices for UI checks; do not issue physical device commands during
layout testing. Check desktop and 390px layouts, keyboard tab navigation, search
and status filters, successful/failed timed actions, cancel-and-restore actions,
custom duration limits, preserved form values, stale service state, and audit
search retention after changing the date period.
