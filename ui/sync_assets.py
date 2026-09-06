"""Copy shared UI assets into each independently deployable Flask service.
Run after editing the canonical files in ui/: python ui/sync_assets.py
"""
from pathlib import Path
import shutil
ROOT = Path(__file__).resolve().parent.parent
FILES = {
    'admin-portal': ['suite.css', 'controls.js'],
    'camera-toggle': ['suite.css', 'controls.js'],
    'door-lock-toggle': ['suite.css', 'controls.js'],
    'hardware-monitor': ['suite.css', 'monitor.js'],
    'audit-viewer': ['suite.css', 'audit.js'],
}
if __name__ == '__main__':
    for service, names in FILES.items():
        target = ROOT / service / 'static'
        target.mkdir(exist_ok=True)
        for name in names:
            shutil.copyfile(ROOT / 'ui' / name, target / name)
