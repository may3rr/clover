"""Text embeddings for excerpt retrieval (AGENTS §5.2: model calls live in
llm/).

Qwen3 embeddings through the OpenAI-compatible ``/embeddings`` endpoints
of DashScope or SiliconFlow, or on this machine through OpenVINO
(``backend = "openvino"``, ``llm/ov.py``), in which case no text leaves
it. Model, endpoint and key variable come from ``[llm.embedding]`` in
config.toml. Synchronous, because excerpts are built
in worker threads. Vectors are L2-normalized
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
from pathlib import Path

import httpx
import numpy as np

from ..cache import Cache, make_key
from ..config import get_settings

log = logging.getLogger(__name__)

# Qwen3-Embedding is instruction-aware on the query side only
_INSTRUCT = ("Instruct: Given a claim from a survey paper, retrieve the passage "
             "of the cited paper that supports or contradicts it\nQuery: ")

_cache: Cache | None = None
# on-device embedder, built on first use; a failed build is not retried
_local = None
_local_error: str | None = None
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


def is_local() -> bool:
    return get_settings().llm.embedding.backend == "openvino"


def enabled() -> bool:
    """Configured, ready and allowed: privacy mode (llm/privacy.py) keeps
    only the on-device backend, so an API backend means BM25 alone."""
    from . import privacy

    s = get_settings()
    cfg = s.llm.embedding
    ready = (bool(cfg.local_model) and _local_error is None) if is_local() \
        else bool(s.embedding_api_key)
    return (cfg.enabled and ready and os.environ.get("CITECHECK_EMBED") != "0"
            and privacy.dense_allowed(is_local()))


def model_id() -> str:
    """Cache-key model name; local and remote vectors never mix."""
    cfg = get_settings().llm.embedding
    if is_local():
        return "ov:" + Path(cfg.local_model).expanduser().name
    return cfg.model


def local_embedder():
    """The OpenVINO embedder, or None when it cannot be built."""
    global _local, _local_error
    with _cache_lock:
        if _local is None and _local_error is None:
            cfg = get_settings().llm.embedding
            try:
                from . import ov

                _local = ov.Embedder(cfg.local_model, cfg.device, cfg.max_length,
                                     get_settings().llm.local.ov_cache_dir)
            except Exception as e:  # noqa: BLE001 — BM25 carries on alone
                _local_error = str(e)
                log.warning("local embedding unavailable (%s); ranking with BM25 only", e)
        return _local


def status() -> dict:
    """For the settings page: where embeddings are computed."""
    e = _local
    return {"backend": get_settings().llm.embedding.backend,
            "device": getattr(e, "device", None), "error": _local_error}


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
    model = model_id()
    keys = [make_key("emb", model, t) for t in inputs]
    cache = _get_cache()
    have = cache.get_vectors(list(dict.fromkeys(keys)))
    todo = list(dict.fromkeys(k for k in keys if k not in have))
    if todo:
        text_of = dict(zip(keys, inputs))
        fresh: dict[str, bytes] = {}
        if is_local():
            return _embed_local(keys, todo, text_of, have, cache)
        try:
            for i in range(0, len(todo), cfg.batch):
                chunk = todo[i:i + cfg.batch]
                sent = [text_of[k] for k in chunk]
                try:
                    vecs, tokens = _request(sent)
                except Exception:
                    _log(cache, "embedding", cfg.model, "cloud", sent, query)
                    raise
                for k, v in zip(chunk, vecs):
                    fresh[k] = v.astype(np.float16).tobytes()
                _log(cache, "embedding", cfg.model, "cloud", sent, query, tokens)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("embedding failed (%s); ranking with BM25 only", e)
            _down_until = time.monotonic() + 60
            if fresh:
                cache.set_vectors(fresh)
            return None
        cache.set_vectors(fresh)
        have.update(fresh)
    return _stack(keys, have)


def _log(cache, provider: str, model: str, route: str, sent: list[str],
         query: bool = False, tokens: int = 0) -> None:
    """Send list row: the windows of cited works are excerpts, a query is
    the claim (instruction prefix stripped from the stored text)."""
    from . import sendlog

    cat = "claim" if query else "excerpt"
    parts = sendlog.pack([(cat, t[len(_INSTRUCT):] if query else t) for t in sent])
    sendlog.record(cache, provider=provider, model=model, task="embed",
                   route=route, prompt=tokens, chars=sum(map(len, sent)),
                   parts=parts if route == "cloud" else None)


def _stack(keys: list[str], have: dict[str, bytes]) -> np.ndarray:
    return np.stack([np.frombuffer(have[k], dtype=np.float16) for k in keys]).astype(np.float32)


def _embed_local(keys, todo, text_of, have, cache) -> np.ndarray | None:
    emb = local_embedder()
    if emb is None:
        return None
    try:
        vecs = emb.embed([text_of[k] for k in todo])
    except Exception as e:  # noqa: BLE001 — BM25 carries on alone
        log.warning("local embedding failed (%s); ranking with BM25 only", e)
        return None
    fresh = {k: v.astype(np.float16).tobytes() for k, v in zip(todo, vecs)}
    cache.set_vectors(fresh)
    _log(cache, "openvino-local", model_id(), "local", [text_of[k] for k in todo])
    have.update(fresh)
    return _stack(keys, have)


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
