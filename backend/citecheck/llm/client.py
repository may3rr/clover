"""Unified LLM access for citecheck (AGENTS §5.2).

Business code calls ``chat_json(task, messages, Schema)`` and gets back a
pydantic-validated value; routing (local vs cloud), caching, retries and
call counting live here. No business module imports openai/mlx directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from ..cache import Cache, make_key
from ..config import get_settings
from . import local
from .router import route_order

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
Route = Literal["local", "cloud"]

_cache: Cache | None = None
_cloud_client: AsyncOpenAI | None = None
_cloud_sem: asyncio.Semaphore | None = None


class LLMStats:
    """Per-job call counters; opened by the pipeline via stats_scope()."""

    def __init__(self) -> None:
        self.local = 0
        self.cloud = 0
        # model -> {"prompt": tokens, "completion": tokens}; real API calls
        # only — cache hits are counted in local/cloud but use no tokens
        self.usage: dict[str, dict[str, int]] = {}


_current_stats: ContextVar[LLMStats | None] = ContextVar("llm_stats", default=None)


class stats_scope:
    """Context manager: ``with stats_scope() as s: ...`` then read
    ``s.local`` / ``s.cloud``. Async contextvars make this per-task safe."""

    def __init__(self) -> None:
        self.stats = LLMStats()
        self._token = None

    def __enter__(self) -> LLMStats:
        self._token = _current_stats.set(self.stats)
        return self.stats

    def __exit__(self, *exc: object) -> None:
        _current_stats.reset(self._token)


def current_stats() -> LLMStats | None:
    return _current_stats.get()


def _count(route: str) -> None:
    s = _current_stats.get()
    if s is not None:
        if route == "local":
            s.local += 1
        else:
            s.cloud += 1


def _record_usage(model: str, usage: Any) -> None:
    s = _current_stats.get()
    if s is None or usage is None:
        return
    u = s.usage.setdefault(model, {"prompt": 0, "completion": 0})
    u["prompt"] += getattr(usage, "prompt_tokens", 0) or 0
    u["completion"] += getattr(usage, "completion_tokens", 0) or 0


def _provider_for(route: str) -> str:
    if route == "local":
        return "mlx-local"
    host = urlparse(get_settings().llm.cloud.base_url).hostname or "cloud"
    if "dashscope" in host or "aliyun" in host:
        return "dashscope"
    return host


def _model_for(route: str, task_model: str) -> str:
    if route == "local":
        return get_settings().llm.local.model
    return task_model


def _log_usage(route: str, task: str, model: str, prompt: int, completion: int,
               cached: bool = False) -> None:
    """Persist one call (or cache hit) into the llm_usage table. Never
    allowed to break the request path."""
    try:
        _get_cache().record_usage(
            _provider_for(route), model, task, prompt, completion, cached
        )
    except Exception as e:  # noqa: BLE001 — stats must never break calls
        log.debug("usage log write failed: %s", e)


def _err_desc(e: BaseException) -> str:
    """Compact error description for logs — status and provider error code
    (e.g. AllocationQuota.FreeTierOnly); never prompt content or keys."""
    desc = type(e).__name__
    status = getattr(e, "status_code", None)
    if status:
        desc += f" status={status}"
    body = getattr(e, "body", None)
    code = None
    if isinstance(body, dict):
        err = body.get("error")
        code = (err or {}).get("code") if isinstance(err, dict) else err
        code = code or body.get("code")
    if code:
        desc += f" code={code}"
    return desc


def _get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache(get_settings().cache_path)
    return _cache


def _get_cloud() -> tuple[AsyncOpenAI, asyncio.Semaphore]:
    global _cloud_client, _cloud_sem
    settings = get_settings()
    if _cloud_client is None:
        _cloud_client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.llm.cloud.base_url,
            timeout=settings.llm.cloud.timeout,
        )
        _cloud_sem = asyncio.Semaphore(settings.llm.cloud.max_concurrency)
    return _cloud_client, _cloud_sem  # type: ignore[return-value]


def _cache_key(model: str, messages: list[dict]) -> str:
    return make_key(model, json.dumps(messages, ensure_ascii=False, sort_keys=True))


@dataclass
class LLMResult:
    value: Any  # validated pydantic instance, or None on failure
    route: Route
    cached: bool = False
    error: str | None = None  # compact error description when value is None


def _ensure_json_word(messages: list[dict]) -> list[dict]:
    """DashScope json_object mode requires the string "json" in messages."""
    blob = " ".join(str(m.get("content", "")) for m in messages)
    if "json" in blob.lower():
        return messages
    return [{"role": "system", "content": "只输出 JSON。"}] + messages


async def _cloud_call(model: str, messages: list[dict], task: str) -> str:
    client, sem = _get_cloud()
    settings = get_settings()
    try:
        async with sem:
            resp = await client.chat.completions.create(
                model=model,
                messages=_ensure_json_word(messages),
                temperature=settings.llm.temperature,
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
            )
    except Exception as e:
        log.warning("cloud call failed model=%s: %s", model, _err_desc(e))
        raise
    _record_usage(model, resp.usage)
    _log_usage(
        "cloud", task, model,
        getattr(resp.usage, "prompt_tokens", 0) or 0,
        getattr(resp.usage, "completion_tokens", 0) or 0,
    )
    return resp.choices[0].message.content or ""


async def _local_call(messages: list[dict], task: str) -> str:
    raw = await local.generate_or_raise(messages)  # raises on failure
    usage = local.last_usage() or {}
    _log_usage(
        "local", task, get_settings().llm.local.model,
        usage.get("prompt", 0), usage.get("completion", 0),
    )
    return raw


def _validate(schema: type[T], text: str) -> T:
    return schema.model_validate(json.loads(text))


async def _attempt(
    schema: type[T], model: str, messages: list[dict], route: str, task: str
) -> tuple[T | None, str | None]:
    """One generation + validation; on invalid output retry once with the
    error appended. Returns (value, raw_text)."""
    if route == "local":
        raw = await _local_call(messages, task)  # raises on failure
    else:
        raw = await _cloud_call(model, messages, task)
    try:
        return _validate(schema, raw), raw
    except (ValidationError, json.JSONDecodeError, TypeError) as e:
        err = str(e)
        retry = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": f"上次输出无法解析为要求的 JSON：{err}。请只输出符合要求的 JSON。",
            },
        ]
        if route == "local":
            raw2 = await _local_call(retry, task)
        else:
            raw2 = await _cloud_call(model, retry, task)
        try:
            return _validate(schema, raw2), raw2
        except (ValidationError, json.JSONDecodeError, TypeError):
            return None, raw2


async def chat_json(
    task: str,
    messages: list[dict],
    schema: type[T],
    *,
    route: str = "auto",
) -> LLMResult:
    """task ∈ judge|review|review_fallback|extract|typo|structure|function
    → configured model.

    Returns LLMResult(value=None) when generation or validation fails on
    every available route; callers map that to undetermined.
    """
    settings = get_settings()
    model = settings.llm.models.model_dump()[task]
    key = _cache_key(model, messages)

    cached = _get_cache().get(key)
    if cached is not None:
        cached_route = cached.get("route", "cloud")
        _count(cached_route)
        _log_usage(cached_route, task, _model_for(cached_route, model), 0, 0,
                   cached=True)
        try:
            value = schema.model_validate(cached["value"])
        except (ValidationError, KeyError):
            value = None
        return LLMResult(value=value, route=cached_route, cached=True)

    order = route_order(task, settings) if route == "auto" else [route]
    last_error: Exception | None = None
    for r in order:
        try:
            value, _raw = await _attempt(schema, model, messages, r, task)
        except Exception as e:  # noqa: BLE001 — route failure -> next route
            log.warning("llm %s route failed for task %s: %s", r, task,
                        _err_desc(e))
            last_error = e
            continue
        _count(r)
        if value is not None:
            _get_cache().set(key, {"route": r, "value": value.model_dump()})
            return LLMResult(value=value, route=r)
        # generated output failed validation -> try the next route too

    log.warning("all routes failed for task %s: %s", task,
                _err_desc(last_error) if last_error else "invalid output")
    return LLMResult(
        value=None, route=order[-1],
        error=_err_desc(last_error) if last_error else "invalid output",
    )
