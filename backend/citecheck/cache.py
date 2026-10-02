"""SQLite key-value cache for retrieval and LLM results (AGENTS.md §5.2).

Values are stored as JSON. Cache keys are produced by make_key(), a sha256
of the joined parts — e.g. sha256(model_name + prompt) for LLM calls.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime
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
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS llm_usage ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "ts TEXT NOT NULL, "
            "provider TEXT NOT NULL, "
            "model TEXT NOT NULL, "
            "task TEXT NOT NULL, "
            "prompt_tokens INTEGER NOT NULL, "
            "completion_tokens INTEGER NOT NULL, "
            "cached INTEGER NOT NULL DEFAULT 0)"
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

    def record_usage(
        self,
        provider: str,
        model: str,
        task: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached: bool = False,
    ) -> None:
        """Append one LLM call to the persistent usage log (llm_usage table).

        Cache hits are recorded with cached=1 and zero tokens so the log
        doubles as a call audit; real calls carry the provider-reported
        token counts (or tokenizer estimates for the local route).
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO llm_usage (ts, provider, model, task, "
                "prompt_tokens, completion_tokens, cached) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    provider,
                    model,
                    task,
                    prompt_tokens,
                    completion_tokens,
                    int(cached),
                ),
            )
            self._conn.commit()

    def usage_summary(self) -> list[dict]:
        """Aggregate the usage log by day + provider + model."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT date(ts) AS day, provider, model, "
                "COUNT(*) AS calls, SUM(cached) AS cached_calls, "
                "SUM(prompt_tokens) AS prompt, "
                "SUM(completion_tokens) AS completion "
                "FROM llm_usage "
                "GROUP BY day, provider, model "
                "ORDER BY day, provider, model"
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
