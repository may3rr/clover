"""Text embeddings for excerpt retrieval (AGENTS §5.2: model calls live in
llm/).

Qwen3-Embedding through an OpenAI-compatible ``/embeddings`` endpoint,
model and endpoint from ``[llm.embedding]`` in config.toml. Synchronous,
because excerpts are built in worker threads. Vectors are L2-normalized
and cached per text (key: model + text) as float16 in the cache's
``vectors`` table. ``embed`` returns None when embeddings are disabled,
no key is set, or the service fails, and retrieval then ranks with BM25
alone.
"""

from __future__ import annotations

import logging
import os
import threading
import time

import httpx
import numpy as np

from ..cache import Cache, make_key
from ..config import get_settings

log = logging.getLogger(__name__)

# Qwen3-Embedding is instruction-aware on the query side only
_INSTRUCT = ("Instruct: Given a claim from a survey paper, retrieve the passage "
             "of the cited paper that supports or contradicts it\nQuery: ")

_cache: Cache | None = None
_cache_lock = threading.Lock()
_sem: threading.Semaphore | None = None
# a failing service is not retried call after call for the rest of a run
_down_until = 0.0


def _get_cache() -> Cache:
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = Cache(get_settings().cache_path)
        return _cache


def enabled() -> bool:
    s = get_settings()
    return (s.llm.embedding.enabled and bool(s.embedding_api_key)
            and os.environ.get("CITECHECK_EMBED") != "0")


def embed(texts: list[str], *, query: bool = False) -> np.ndarray | None:
    """(len(texts), dim) unit vectors, or None when unavailable."""
    global _sem, _down_until
    if not texts or not enabled() or time.monotonic() < _down_until:
        return None
    cfg = get_settings().llm.embedding
    with _cache_lock:
        if _sem is None:
            _sem = threading.Semaphore(cfg.max_concurrency)
    inputs = [_INSTRUCT + t if query else t for t in texts]
    keys = [make_key("emb", cfg.model, t) for t in inputs]
    cache = _get_cache()
    have = cache.get_vectors(list(dict.fromkeys(keys)))
    todo = list(dict.fromkeys(k for k in keys if k not in have))
    if todo:
        text_of = dict(zip(keys, inputs))
        fresh: dict[str, bytes] = {}
        try:
            for i in range(0, len(todo), cfg.batch):
                chunk = todo[i:i + cfg.batch]
                vecs, tokens = _request([text_of[k] for k in chunk])
                for k, v in zip(chunk, vecs):
                    fresh[k] = v.astype(np.float16).tobytes()
                cache.record_usage("embedding", cfg.model, "embed", prompt_tokens=tokens)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("embedding failed (%s); ranking with BM25 only", e)
            _down_until = time.monotonic() + 60
            if fresh:
                cache.set_vectors(fresh)
            return None
        cache.set_vectors(fresh)
        have.update(fresh)
    return np.stack([np.frombuffer(have[k], dtype=np.float16) for k in keys]).astype(np.float32)


def _request(inputs: list[str]) -> tuple[list[np.ndarray], int]:
    s = get_settings()
    cfg = s.llm.embedding
    assert _sem is not None
    with _sem:
        for attempt in range(3):
            try:
                r = httpx.post(
                    cfg.base_url.rstrip("/") + "/embeddings",
                    headers={"Authorization": f"Bearer {s.embedding_api_key}"},
                    json={"model": cfg.model, "input": inputs},
                    timeout=cfg.timeout,
                )
                r.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
    data = r.json()
    rows = sorted(data["data"], key=lambda d: d["index"])
    vecs = []
    for row in rows:
        v = np.asarray(row["embedding"], dtype=np.float32)
        vecs.append(v / (np.linalg.norm(v) or 1.0))
    if len(vecs) != len(inputs):
        raise ValueError(f"expected {len(inputs)} vectors, got {len(vecs)}")
    return vecs, int(data.get("usage", {}).get("total_tokens", 0))
