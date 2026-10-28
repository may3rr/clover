"""Cross-encoder reranking for excerpt retrieval (AGENTS §5.2: model calls
live in llm/).

Qwen3-Reranker through a ``/rerank`` endpoint (model and endpoint from
``[llm.rerank]``). Synchronous, like ``embed``: excerpts are built in
worker threads. Scores are cached per (model, query, candidate list).
``rerank`` returns None when reranking is disabled, no key is set, or the
service fails; the fused ranking then stands.
"""

from __future__ import annotations

import logging
import os
import threading
import time

import httpx

from ..cache import Cache, make_key
from ..config import get_settings

log = logging.getLogger(__name__)

_cache: Cache | None = None
_lock = threading.Lock()
# the rerank endpoint rate-limits hard: few requests in flight, and a 429
# waits and retries instead of switching reranking off
_sem = threading.Semaphore(2)
_down_until = 0.0


def _key() -> str | None:
    s = get_settings()
    return os.environ.get(s.llm.rerank.api_key_env) or s.embedding_api_key


def enabled() -> bool:
    return (get_settings().llm.rerank.enabled and bool(_key())
            and os.environ.get("CITECHECK_RERANK") != "0")


def rerank(query: str, docs: list[str]) -> list[float] | None:
    global _cache, _down_until
    if not docs or not enabled() or time.monotonic() < _down_until:
        return None
    cfg = get_settings().llm.rerank
    with _lock:
        if _cache is None:
            _cache = Cache(get_settings().cache_path)
    key = make_key("rerank", cfg.model, query, *docs)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    try:
        r = None
        for attempt in range(6):
            try:
                with _sem:
                    r = httpx.post(
                        cfg.base_url.rstrip("/") + "/rerank",
                        headers={"Authorization": f"Bearer {_key()}"},
                        json={"model": cfg.model, "query": query, "documents": docs,
                              "return_documents": False},
                        timeout=cfg.timeout,
                    )
                if r.status_code == 429 and attempt < 5:
                    time.sleep(float(r.headers.get("retry-after") or 2 ** attempt))
                    continue
                r.raise_for_status()
                break
            except httpx.TransportError:
                if attempt == 5:
                    raise
                time.sleep(2 * (attempt + 1))
        data = r.json()
        scores = [0.0] * len(docs)
        for row in data["results"]:
            scores[row["index"]] = float(row["relevance_score"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        log.warning("rerank failed (%s); keeping the fused ranking", e)
        _down_until = time.monotonic() + 60
        return None
    tokens = data.get("meta", {}).get("tokens", {}).get("input_tokens", 0)
    _cache.record_usage("rerank", cfg.model, "rerank", prompt_tokens=tokens)
    _cache.set(key, scores)
    return scores
