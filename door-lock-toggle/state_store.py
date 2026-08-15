"""Durable state for timed door unlocks and physical-button requests."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    """Serialize a timestamp in UTC with second precision."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(value: str) -> datetime:
    """Parse a stored timestamp, treating legacy naive values as UTC."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class DoorStateStore:
    """Small SQLite repository shared by the web app and safety script."""

    def __init__(self, path: str):
        self.path = str(path)
        self._schema_lock = threading.Lock()
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        with self._schema_lock:
            parent = Path(self.path).expanduser().resolve().parent
            parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS timed_unlocks (
                        door_id TEXT PRIMARY KEY,
                        door_name TEXT NOT NULL,
                        unlock_at TEXT NOT NULL,
                        lock_at TEXT NOT NULL,
                        duration_min INTEGER NOT NULL,
                        source TEXT NOT NULL,
                        request_id TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS button_requests (
                        request_id TEXT PRIMARY KEY,
                        device_id TEXT NOT NULL,
                        door_id TEXT NOT NULL,
                        action_taken TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_timed_unlocks_lock_at
                        ON timed_unlocks(lock_at);
                    CREATE INDEX IF NOT EXISTS idx_button_requests_created_at
                        ON button_requests(created_at);
                    """
                )
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    def save_timed_unlock(
        self,
        door_id: str,
        door_name: str,
        unlock_at: datetime,
        lock_at: datetime,
        duration_min: int,
        source: str,
        request_id: str | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        created_at = created_at or utc_now()
        values = (
            door_id,
            door_name,
            to_iso(unlock_at),
            to_iso(lock_at),
            int(duration_min),
            source,
            request_id,
            to_iso(created_at),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO timed_unlocks (
                    door_id, door_name, unlock_at, lock_at, duration_min,
                    source, request_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(door_id) DO UPDATE SET
                    door_name = excluded.door_name,
                    unlock_at = excluded.unlock_at,
                    lock_at = excluded.lock_at,
                    duration_min = excluded.duration_min,
                    source = excluded.source,
                    request_id = excluded.request_id,
                    created_at = excluded.created_at
                """,
                values,
            )
        return self.get_timed_unlock(door_id)

    def get_timed_unlock(self, door_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM timed_unlocks WHERE door_id = ?", (door_id,)
            ).fetchone()
        return self._row(row)

    def list_timed_unlocks(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM timed_unlocks ORDER BY lock_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_expired_timed_unlocks(self, now: datetime | None = None) -> list[dict]:
        cutoff = to_iso(now or utc_now())
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM timed_unlocks WHERE lock_at <= ? ORDER BY lock_at",
                (cutoff,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_timed_unlock(self, door_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM timed_unlocks WHERE door_id = ?", (door_id,)
            )
        return cursor.rowcount > 0

    @staticmethod
    def is_valid_active_unlock(row: dict | None, now: datetime | None = None) -> bool:
        if not row:
            return False
        now = now or utc_now()
        try:
            unlock_at = from_iso(row["unlock_at"])
            lock_at = from_iso(row["lock_at"])
            duration_min = int(row["duration_min"])
        except (KeyError, TypeError, ValueError):
            return False
        if duration_min < 1 or duration_min > 480:
            return False
        expected_latest = unlock_at + timedelta(minutes=duration_min, seconds=1)
        return unlock_at <= lock_at <= expected_latest and lock_at > now

    def active_timer_views(self, now: datetime | None = None) -> dict[str, dict]:
        now = now or utc_now()
        result = {}
        for row in self.list_timed_unlocks():
            if not self.is_valid_active_unlock(row, now):
                continue
            lock_at = from_iso(row["lock_at"])
            result[row["door_id"]] = {
                "name": row["door_name"],
                "remaining_sec": max(0, int((lock_at - now).total_seconds())),
                "duration_min": int(row["duration_min"]),
                "lock_at": to_iso(lock_at),
                "source": row["source"],
            }
        return result

    def get_button_request(self, request_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM button_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        result = self._row(row)
        if result:
            result["result"] = json.loads(result.pop("result_json"))
        return result

    def save_button_request(
        self,
        request_id: str,
        device_id: str,
        door_id: str,
        action_taken: str,
        result: dict,
        created_at: datetime | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO button_requests (
                    request_id, device_id, door_id, action_taken,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    device_id,
                    door_id,
                    action_taken,
                    json.dumps(result, sort_keys=True, separators=(",", ":")),
                    to_iso(created_at or utc_now()),
                ),
            )

    def begin_button_request(
        self,
        request_id: str,
        device_id: str,
        door_id: str,
        created_at: datetime | None = None,
    ) -> bool:
        """Reserve an idempotency key before touching the physical door."""
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO button_requests (
                        request_id, device_id, door_id, action_taken,
                        result_json, created_at
                    ) VALUES (?, ?, ?, 'pending', '{}', ?)
                    """,
                    (request_id, device_id, door_id, to_iso(created_at or utc_now())),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def complete_button_request(
        self, request_id: str, action_taken: str, result: dict
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE button_requests
                SET action_taken = ?, result_json = ?
                WHERE request_id = ? AND action_taken = 'pending'
                """,
                (
                    action_taken,
                    json.dumps(result, sort_keys=True, separators=(",", ":")),
                    request_id,
                ),
            )
        if cursor.rowcount != 1:
            raise RuntimeError(f"button request {request_id} was not pending")

    def prune_button_requests(
        self, older_than: timedelta = timedelta(hours=24), now: datetime | None = None
    ) -> int:
        cutoff = to_iso((now or utc_now()) - older_than)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM button_requests WHERE created_at < ?", (cutoff,)
            )
        return cursor.rowcount
