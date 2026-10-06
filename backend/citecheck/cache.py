"""SQLite key-value cache for retrieval and LLM results (AGENTS.md §5.2).

Values are stored as JSON. Cache keys are produced by make_key(): a
readable ``"<first-part>|"`` prefix (the source or model name) followed by
a sha256 of the joined parts — e.g. ``"qwen3.8-flash|<digest>"`` for LLM
calls, ``"crossref|<digest>"`` for retrieval calls. The prefix drives
per-class TTLs: retrieval records go stale (databases correct their
metadata), LLM verdicts are kept until deliberately invalidated via
``cache_version`` in config.toml.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Retrieval results expire: Crossref/OpenAlex/S2/arXiv records get corrected
# upstream, and a stale cached "no hit" must not block a later verification.
_RETRIEVAL_TTL = 30 * 86400  # seconds
# Key prefixes that identify retrieval entries (LLM keys start with the
# model name and never expire — bump settings.cache_version to clear them).
_TTL_PREFIXES = ("crossref|", "openalex|", "s2|", "arxiv", "pdftext|",
                 "anthology-volume|")


def make_key(*parts: object) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\x00")
    digest = h.hexdigest()
    return f"{parts[0]}|{digest}" if parts else digest


class Cache:
    """Thread-safe SQLite KV store. One connection, WAL, guarded by a lock."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # WAL + NORMAL: commits no longer fsync (only checkpoints do). A
        # crash can lose the last few cache rows, never corrupt the file —
        # fine for a cache, and every set() stops stalling the event loop
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # several Cache instances (server, LLM client, pipeline) share the
        # file; wait for a writer instead of failing with "locked"
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(kv)")}
        if "created_at" not in cols:
            self._conn.execute(
                "ALTER TABLE kv ADD COLUMN created_at INTEGER")
            # rows written before the column existed: treat as fresh
            self._conn.execute(
                "UPDATE kv SET created_at = ?", (int(time.time()),))
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
        cols = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(llm_usage)")}
        if "doc" not in cols:
            self._conn.execute(
                "ALTER TABLE llm_usage ADD COLUMN doc TEXT")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS reports ("
            "id TEXT PRIMARY KEY, "
            "filename TEXT NOT NULL, "
            "title TEXT NOT NULL, "
            "src_path TEXT NOT NULL, "
            "benchmark TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "n_high INTEGER NOT NULL DEFAULT 0, "
            "n_medium INTEGER NOT NULL DEFAULT 0, "
            "n_low INTEGER NOT NULL DEFAULT 0, "
            "report_json TEXT NOT NULL)")
        self._conn.commit()

    def _expired(self, key: str, created_at: int | None) -> bool:
        """Retrieval keys older than their TTL are stale; everything else
        (LLM verdicts) lives until cache_version invalidates it."""
        if created_at is None or not key.startswith(_TTL_PREFIXES):
            return False
        return time.time() - created_at > _RETRIEVAL_TTL

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, created_at FROM kv WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value, created_at = row
        if self._expired(key, created_at):
            with self._lock:
                self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
                self._conn.commit()
            return None
        return json.loads(value)

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value, created_at) "
                "VALUES (?, ?, ?)",
                (key, payload, int(time.time())),
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
        doc: str | None = None,
    ) -> None:
        """Append one LLM call to the persistent usage log (llm_usage table).

        Cache hits are recorded with cached=1 and zero tokens so the log
        doubles as a call audit; real calls carry the provider-reported
        token counts (or tokenizer estimates for the local route).
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO llm_usage (ts, provider, model, task, "
                "prompt_tokens, completion_tokens, cached, doc) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    provider,
                    model,
                    task,
                    prompt_tokens,
                    completion_tokens,
                    int(cached),
                    doc,
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

    def usage_grouped(self, keys: list[str]) -> list[dict]:
        """Aggregate llm_usage by an arbitrary whitelist of columns
        (day/provider/model/task/doc)."""
        allowed = {"provider", "model", "task", "doc"}
        exprs = ["date(ts) AS day" if k == "day" else
                 f"COALESCE({k}, '') AS {k}" for k in keys
                 if k in allowed or k == "day"]
        if not exprs:
            return []
        group_cols = ", ".join(k if k != "day" else "day" for k in keys)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT {', '.join(exprs)}, "
                "COUNT(*) AS calls, SUM(cached) AS cached_calls, "
                "SUM(prompt_tokens) AS prompt, "
                "SUM(completion_tokens) AS completion "
                f"FROM llm_usage GROUP BY {group_cols} "
                f"ORDER BY {group_cols}"
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def save_report(
        self,
        report_id: str,
        filename: str,
        title: str,
        src_path: str,
        benchmark: str,
        severity_counts: dict[str, int],
        report_json: str,
    ) -> None:
        """Persist a finished check report so the home screen can list and
        reopen past results without re-running the pipeline."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO reports (id, filename, title, "
                "src_path, benchmark, created_at, n_high, n_medium, n_low, "
                "report_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    report_id,
                    filename,
                    title,
                    src_path,
                    benchmark,
                    datetime.now().isoformat(timespec="seconds"),
                    severity_counts.get("high", 0),
                    severity_counts.get("medium", 0),
                    severity_counts.get("low", 0),
                    report_json,
                ),
            )
            self._conn.commit()

    def list_reports(self) -> list[dict]:
        """Sidebar listing — metadata only, newest first."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, filename, title, created_at, "
                "n_high, n_medium, n_low "
                "FROM reports ORDER BY created_at DESC, rowid DESC"
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_report(self, report_id: str) -> dict | None:
        """Full row incl. src_path and the report JSON blob."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, filename, title, src_path, benchmark, "
                "created_at, report_json FROM reports WHERE id = ?",
                (report_id,),
            ).fetchone()
        if row is None:
            return None
        cols = ["id", "filename", "title", "src_path", "benchmark",
                "created_at", "report_json"]
        return dict(zip(cols, row))

    def delete_report(self, report_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM reports WHERE id = ?", (report_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
