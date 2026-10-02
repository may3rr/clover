"""SQLite key-value cache for retrieval and LLM results (AGENTS.md §5.2).

Values are stored as JSON. Cache keys are produced by make_key(), a sha256
of the joined parts — e.g. sha256(model_name + prompt) for LLM calls.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


def make_key(*parts: object) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class Cache:
    """Thread-safe SQLite KV store. One connection, WAL, guarded by a lock."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM kv WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                (key, payload),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
