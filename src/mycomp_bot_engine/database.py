from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(data_dir, 0o700)
        self.path = data_dir / "state.sqlite3"
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        os.chmod(self.path, 0o600)
        self.connection.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS capabilities (name TEXT PRIMARY KEY, state TEXT NOT NULL, checksum TEXT NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS capability_versions (name TEXT NOT NULL, checksum TEXT NOT NULL, source BLOB NOT NULL, tested INTEGER NOT NULL DEFAULT 0, test_error TEXT, created REAL NOT NULL, PRIMARY KEY(name, checksum))")
        self.connection.execute("CREATE TABLE IF NOT EXISTS capability_history (id INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS capability_metadata (name TEXT NOT NULL, checksum TEXT NOT NULL, version TEXT NOT NULL, description TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(name, checksum))")
        self.connection.commit()
        # Existing local state from an early development build may lack this column.
        try:
            self.connection.execute("ALTER TABLE capability_versions ADD COLUMN test_error TEXT")
            self.connection.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self.connection.execute("ALTER TABLE capability_metadata ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
            self.connection.commit()
        except sqlite3.OperationalError:
            pass

    def close(self) -> None:
        """Close the shared SQLite connection once runtime shutdown is complete."""
        with self._lock:
            if getattr(self, "_closed", False):
                return
            self.connection.close()
            self._closed = True

    def save_job(self, job_id: str, state: str, payload: dict[str, Any]) -> None:
        payload = {key: value for key, value in payload.items() if key not in {"id", "state"}}
        with self._lock:
            self.connection.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?, ?)", (job_id, state, json.dumps(payload)))
            self.connection.commit()

    def transition_job(self, job_id: str, expected: set[str], state: str, payload: dict[str, Any]) -> bool:
        """Atomically change a job only when it is still in an expected state."""
        payload = {key: value for key, value in payload.items() if key not in {"id", "state"}}
        with self._lock:
            marks = ",".join("?" for _ in expected)
            cursor = self.connection.execute(
                f"UPDATE jobs SET state = ?, payload = ? WHERE id = ? AND state IN ({marks})",
                (state, json.dumps(payload), job_id, *expected),
            )
            self.connection.commit()
            return cursor.rowcount == 1

    def transaction(self):
        return self._lock

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute("SELECT state, payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return {**json.loads(row[1]), "id": job_id, "state": row[0]} if row else None
