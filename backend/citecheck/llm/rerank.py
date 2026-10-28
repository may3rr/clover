"""Cross-encoder reranking for excerpt retrieval (AGENTS §5.2: model calls
live in llm/).

Qwen3 rerankers through SiliconFlow's ``/rerank`` endpoint or DashScope's
native rerank endpoint. Model, endpoint, key variable and API format come
from ``[llm.rerank]``. Synchronous, like ``embed``: excerpts are built in
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
    return get_settings().rerank_api_key


def enabled() -> bool:
    return (get_settings().llm.rerank.enabled and bool(_key())
            and os.environ.get("CITECHECK_RERANK") != "0")


def _request(query: str, docs: list[str]) -> tuple[list[float], int]:
    cfg = get_settings().llm.rerank
    if cfg.api_format == "dashscope":
        url = cfg.base_url
        payload = {
            "model": cfg.model,
            "input": {"query": query, "documents": docs},
            "parameters": {"return_documents": False},
        }
    else:
        url = cfg.base_url.rstrip("/") + "/rerank"
        payload = {"model": cfg.model, "query": query, "documents": docs,
                   "return_documents": False}
    r = None
    for attempt in range(6):
        try:
            with _sem:
                r = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {_key()}"},
                    json=payload,
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
    rows = data["output"]["results"] if cfg.api_format == "dashscope" else data["results"]
    scores = [0.0] * len(docs)
    for row in rows:
        scores[row["index"]] = float(row["relevance_score"])
    if cfg.api_format == "dashscope":
        tokens = data.get("usage", {}).get("total_tokens", 0)
    else:
        tokens = data.get("meta", {}).get("tokens", {}).get("input_tokens", 0)
    return scores, int(tokens)


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
        scores, tokens = _request(query, docs)
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        log.warning("rerank failed (%s); keeping the fused ranking", e)
        _down_until = time.monotonic() + 60
        return None
    _cache.record_usage("rerank", cfg.model, "rerank", prompt_tokens=tokens)
    _cache.set(key, scores)
    return scores
