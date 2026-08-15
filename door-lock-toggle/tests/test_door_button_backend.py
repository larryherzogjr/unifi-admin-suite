import importlib.util
import sys
import tempfile
import threading
import types
import unittest
import uuid
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock


SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

from state_store import DoorStateStore, utc_now


MODULE_TEMP = tempfile.TemporaryDirectory()
fake_config = types.ModuleType("config")
fake_config.ACCESS_HOST = "access.test"
fake_config.ACCESS_PORT = 12445
fake_config.API_TOKEN = "upstream-token"
fake_config.VERIFY_SSL = False
fake_config.FLASK_HOST = "127.0.0.1"
fake_config.FLASK_PORT = 5001
fake_config.FLASK_DEBUG = False
fake_config.INCLUDED_DOORS = []
fake_config.MAX_RETRIES = 1
fake_config.RETRY_DELAY = 0
fake_config.REQUEST_TIMEOUT = 1
fake_config.UNIFI_NETWORK = None
fake_config.STATE_DB_PATH = str(Path(MODULE_TEMP.name) / "import.db")
fake_config.BUTTON_UNLOCK_MINUTES = 180
fake_config.BUTTON_REQUEST_TTL_HOURS = 24
fake_config.DOOR_CACHE_INTERVAL = 5
fake_config.DOOR_CACHE_MAX_AGE = 30
fake_config.DEADLINE_SWEEP_INTERVAL = 15
fake_config.DOOR_CONFIRM_ATTEMPTS = 1
fake_config.DOOR_CONFIRM_DELAY = 0
fake_config.BUTTON_DEVICES = {
    "button-test-01": {"token": "test-token", "door_ids": ["door-1"]}
}
sys.modules["config"] = fake_config


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SERVICE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


door_app = load_module("door_button_app", "app.py")
safety = load_module("door_safety_app", "ensure_all_locked.py")


class FakeAccess:
    def __init__(self):
        self.doors = {
            "door-1": {
                "id": "door-1",
                "name": "Main Entrance",
                "type": "door",
                "door_lock_relay_status": "lock",
                "door_position_status": "closed",
            }
        }
        self.list_calls = 0
        self.lock_calls = 0
        self.unlock_calls = 0
        self.fail_list = False
        self.fail_lock = False
        self.fail_unlock = False
        self.raise_after_unlock = False

    def list_doors(self):
        self.list_calls += 1
        if self.fail_list:
            raise RuntimeError("controller unavailable")
        return [dict(door) for door in self.doors.values()]

    @staticmethod
    def door_summary(door):
        lock_status = door.get("door_lock_relay_status", "unknown")
        return {
            "id": door["id"],
            "name": door["name"],
            "type": door.get("type", ""),
            "lockRule": lock_status,
            "isUnlocked": lock_status == "unlock",
            "doorStatus": door.get("door_position_status", ""),
        }

    def lock_door(self, door_id):
        self.lock_calls += 1
        if self.fail_lock:
            raise RuntimeError("lock failed")
        self.doors[door_id]["door_lock_relay_status"] = "lock"

    def unlock_door(self, door_id):
        self.unlock_calls += 1
        if self.fail_unlock:
            raise RuntimeError("unlock failed")
        self.doors[door_id]["door_lock_relay_status"] = "unlock"
        if self.raise_after_unlock:
            raise RuntimeError("response lost after unlock")


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "state.db")
        self.store = DoorStateStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_deadline_survives_new_store_instance(self):
        now = utc_now()
        self.store.save_timed_unlock(
            "door-1", "Main Entrance", now, now + timedelta(hours=3), 180, "web"
        )
        reopened = DoorStateStore(self.path)
        row = reopened.get_timed_unlock("door-1")
        self.assertEqual(row["duration_min"], 180)
        self.assertTrue(reopened.is_valid_active_unlock(row, now))

    def test_invalid_or_expired_deadline_is_not_active(self):
        now = utc_now()
        row = self.store.save_timed_unlock(
            "door-1", "Main Entrance", now - timedelta(hours=4), now - timedelta(hours=1), 180, "web"
        )
        self.assertFalse(self.store.is_valid_active_unlock(row, now))
        self.assertEqual(len(self.store.list_expired_timed_unlocks(now)), 1)

    def test_pending_request_completes_and_replays(self):
        request_id = str(uuid.uuid4())
        self.assertTrue(self.store.begin_button_request(request_id, "button-1", "door-1"))
        self.assertFalse(self.store.begin_button_request(request_id, "button-1", "door-1"))
        self.assertEqual(self.store.get_button_request(request_id)["action_taken"], "pending")
        result = {"door_id": "door-1", "locked": False}
        self.store.complete_button_request(request_id, "unlocked_180", result)
        self.assertEqual(self.store.get_button_request(request_id)["result"], result)


class ButtonApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        door_app.state_store = DoorStateStore(str(Path(self.temp.name) / "state.db"))
        door_app.access_api = FakeAccess()
        door_app.audit_helper.write = Mock()
        door_app._door_locks = defaultdict(threading.Lock)
        with door_app._door_cache_lock:
            door_app._door_cache = {}
            door_app._door_cache_refreshed_at = None
            door_app._door_cache_error = None
        door_app._fetch_live_doors()
        door_app.app.config.update(TESTING=True)
        self.client = door_app.app.test_client()
        self.headers = {"Authorization": "Bearer test-token"}

    def tearDown(self):
        self.temp.cleanup()

    def post_toggle(self, request_id=None, **extra):
        body = {
            "door_id": "door-1",
            "request_id": request_id or str(uuid.uuid4()),
            "duration_min": 180,
        }
        body.update(extra)
        return self.client.post(
            "/api/button/v1/toggle", json=body, headers=self.headers
        )

    def test_state_requires_auth_and_uses_cache(self):
        response = self.client.get("/api/button/v1/state?door_id=door-1")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(door_app.access_api.list_calls, 1)

        response = self.client.get(
            "/api/button/v1/state?door_id=door-1",
            headers={"Authorization": "Bearer n\N{LATIN SMALL LETTER O WITH DIAERESIS}pe"},
        )
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            "/api/button/v1/state?door_id=door-1", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["locked"])
        self.assertEqual(door_app.access_api.list_calls, 1)

    def test_state_rejects_stale_cache(self):
        with door_app._door_cache_lock:
            door_app._door_cache_refreshed_at = utc_now() - timedelta(seconds=31)
        response = self.client.get(
            "/api/button/v1/state?door_id=door-1", headers=self.headers
        )
        self.assertEqual(response.status_code, 503)

    def test_locked_press_unlocks_for_fixed_duration_and_replay_is_safe(self):
        request_id = str(uuid.uuid4())
        first = self.post_toggle(request_id)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.get_json()["locked"])
        self.assertFalse(first.get_json()["replayed"])
        self.assertEqual(door_app.access_api.unlock_calls, 1)
        row = door_app.state_store.get_timed_unlock("door-1")
        self.assertEqual(row["duration_min"], 180)
        self.assertEqual(row["source"], "button:button-test-01")

        replay = self.post_toggle(request_id)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.get_json()["replayed"])
        self.assertEqual(door_app.access_api.unlock_calls, 1)

    def test_uuid_is_canonicalized_before_idempotency_lookup(self):
        request_id = str(uuid.uuid4())
        first = self.post_toggle(request_id.upper())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["request_id"], request_id)

        replay = self.post_toggle(request_id)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.get_json()["replayed"])
        self.assertEqual(door_app.access_api.unlock_calls, 1)

    def test_non_object_json_is_rejected_without_door_action(self):
        response = self.client.post(
            "/api/button/v1/toggle", json=["not", "an", "object"], headers=self.headers
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(door_app.access_api.lock_calls, 0)
        self.assertEqual(door_app.access_api.unlock_calls, 0)

    def test_green_press_locks_and_clears_deadline(self):
        self.assertEqual(self.post_toggle().status_code, 200)
        second = self.post_toggle()
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["locked"])
        self.assertEqual(door_app.access_api.lock_calls, 1)
        self.assertIsNone(door_app.state_store.get_timed_unlock("door-1"))

    def test_duration_is_fixed_and_door_is_token_scoped(self):
        response = self.post_toggle(duration_min=60)
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/button/v1/toggle",
            json={"door_id": "door-2", "request_id": str(uuid.uuid4()), "duration_min": 180},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(door_app.access_api.unlock_calls, 0)

    def test_concurrent_operation_returns_conflict(self):
        lock = door_app._get_door_lock("door-1")
        lock.acquire()
        try:
            response = self.post_toggle()
        finally:
            lock.release()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(door_app.access_api.unlock_calls, 0)

    def test_lost_command_response_is_confirmed_as_success(self):
        door_app.access_api.raise_after_unlock = True
        response = self.post_toggle()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["locked"])
        self.assertIsNotNone(door_app.state_store.get_timed_unlock("door-1"))

    def test_expired_deadline_retries_until_lock_is_confirmed(self):
        now = utc_now()
        door_app.access_api.doors["door-1"]["door_lock_relay_status"] = "unlock"
        door_app.state_store.save_timed_unlock(
            "door-1",
            "Main Entrance",
            now - timedelta(hours=3),
            now - timedelta(seconds=1),
            180,
            "button:button-test-01",
        )
        door_app.access_api.fail_lock = True
        self.assertEqual(door_app._sweep_expired_unlocks(now), 0)
        self.assertIsNotNone(door_app.state_store.get_timed_unlock("door-1"))

        door_app.access_api.fail_lock = False
        self.assertEqual(door_app._sweep_expired_unlocks(now), 1)
        self.assertIsNone(door_app.state_store.get_timed_unlock("door-1"))
        self.assertEqual(
            door_app.access_api.doors["door-1"]["door_lock_relay_status"], "lock"
        )


class SafetyReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DoorStateStore(str(Path(self.temp.name) / "state.db"))
        self.access = FakeAccess()
        safety.access_api = self.access

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_unlock_crossing_7pm_is_preserved(self):
        now = utc_now()
        self.access.doors["door-1"]["door_lock_relay_status"] = "unlock"
        self.store.save_timed_unlock(
            "door-1", "Main Entrance", now, now + timedelta(hours=3), 180, "web"
        )
        result = safety.run_safety_check(store=self.store, now=now)
        self.assertEqual(result["preserved"], 1)
        self.assertEqual(self.access.lock_calls, 0)

    def test_overdue_unlock_is_locked_and_cleaned(self):
        now = utc_now()
        self.access.doors["door-1"]["door_lock_relay_status"] = "unlock"
        self.store.save_timed_unlock(
            "door-1",
            "Main Entrance",
            now - timedelta(hours=3),
            now - timedelta(seconds=1),
            180,
            "web",
        )
        result = safety.run_safety_check(store=self.store, now=now)
        self.assertEqual(result["fixed"], 1)
        self.assertIsNone(self.store.get_timed_unlock("door-1"))

    def test_failed_safety_lock_retains_deadline(self):
        now = utc_now()
        self.access.doors["door-1"]["door_lock_relay_status"] = "unlock"
        self.access.fail_lock = True
        self.store.save_timed_unlock(
            "door-1",
            "Main Entrance",
            now - timedelta(hours=3),
            now - timedelta(seconds=1),
            180,
            "web",
        )
        result = safety.run_safety_check(store=self.store, now=now)
        self.assertEqual(result["failed"], 1)
        self.assertIsNotNone(self.store.get_timed_unlock("door-1"))

    def test_dry_run_does_not_lock_or_delete(self):
        now = utc_now()
        self.access.doors["door-1"]["door_lock_relay_status"] = "unlock"
        self.store.save_timed_unlock(
            "door-1",
            "Main Entrance",
            now - timedelta(hours=3),
            now - timedelta(seconds=1),
            180,
            "web",
        )
        result = safety.run_safety_check(dry_run=True, store=self.store, now=now)
        self.assertEqual(result["candidates"], 1)
        self.assertEqual(self.access.lock_calls, 0)
        self.assertIsNotNone(self.store.get_timed_unlock("door-1"))


if __name__ == "__main__":
    unittest.main()
