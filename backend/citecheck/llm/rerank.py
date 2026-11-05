"""Cross-encoder reranking for excerpt retrieval (AGENTS §5.2: model calls
live in llm/).

Qwen3 rerankers through SiliconFlow's ``/rerank`` endpoint or DashScope's
native rerank endpoint, or on this machine through OpenVINO
(``backend = "openvino"``, ``llm/ov.py``). Model, endpoint, key variable
and API format come from ``[llm.rerank]``. Synchronous, like ``embed``: excerpts are built in
worker threads. Scores are cached per (model, query, candidate list).
``rerank`` returns None when reranking is disabled, no key is set, or the
service fails; the fused ranking then stands.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

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
# on-device reranker, built on first use; a failed build is not retried
_local = None
_local_error: str | None = None
_local_lock = threading.Lock()


def _key() -> str | None:
    return get_settings().rerank_api_key


def is_local() -> bool:
    return get_settings().llm.rerank.backend == "openvino"


def enabled() -> bool:
    cfg = get_settings().llm.rerank
    ready = (bool(cfg.local_model) and _local_error is None) if is_local() else bool(_key())
    return cfg.enabled and ready and os.environ.get("CITECHECK_RERANK") != "0"


def model_id() -> str:
    cfg = get_settings().llm.rerank
    if is_local():
        return "ov:" + Path(cfg.local_model).expanduser().name
    return cfg.model


def local_reranker():
    global _local, _local_error
    with _local_lock:
        if _local is None and _local_error is None:
            cfg = get_settings().llm.rerank
            try:
                from . import ov

                _local = ov.Reranker(cfg.local_model, cfg.device, cfg.max_length,
                                     get_settings().llm.local.ov_cache_dir)
            except Exception as e:  # noqa: BLE001 — the fused ranking stands
                _local_error = str(e)
                log.warning("local rerank unavailable (%s); keeping the fused ranking", e)
        return _local


def status() -> dict:
    e = _local
    return {"backend": get_settings().llm.rerank.backend,
            "device": getattr(e, "device", None), "error": _local_error}


def _request_local(query: str, docs: list[str]) -> tuple[list[float], int]:
    rr = local_reranker()
    if rr is None:
        raise ValueError(_local_error or "local reranker unavailable")
    return rr.rerank(query, docs), 0


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
    with _lock:
        if _cache is None:
            _cache = Cache(get_settings().cache_path)
    model = model_id()
    key = make_key("rerank", model, query, *docs)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    local = is_local()
    try:
        scores, tokens = (_request_local if local else _request)(query, docs)
    except (httpx.HTTPError, KeyError, ValueError, TypeError, RuntimeError) as e:
        log.warning("rerank failed (%s); keeping the fused ranking", e)
        _down_until = time.monotonic() + 60
        return None
    _cache.record_usage("openvino-local" if local else "rerank", model, "rerank",
                        prompt_tokens=tokens)
    _cache.set(key, scores)
    return scores
