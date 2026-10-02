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


def _ensure_json_word(messages: list[dict]) -> list[dict]:
    """DashScope json_object mode requires the string "json" in messages."""
    blob = " ".join(str(m.get("content", "")) for m in messages)
    if "json" in blob.lower():
        return messages
    return [{"role": "system", "content": "只输出 JSON。"}] + messages


async def _cloud_call(model: str, messages: list[dict]) -> str:
    client, sem = _get_cloud()
    settings = get_settings()
    async with sem:
        resp = await client.chat.completions.create(
            model=model,
            messages=_ensure_json_word(messages),
            temperature=settings.llm.temperature,
            response_format={"type": "json_object"},
            extra_body={"enable_thinking": False},
        )
    return resp.choices[0].message.content or ""


def _validate(schema: type[T], text: str) -> T:
    return schema.model_validate(json.loads(text))


async def _attempt(
    schema: type[T], model: str, messages: list[dict], route: str
) -> tuple[T | None, str | None]:
    """One generation + validation; on invalid output retry once with the
    error appended. Returns (value, raw_text)."""
    if route == "local":
        raw = await local.generate_or_raise(messages)  # raises on failure
    else:
        raw = await _cloud_call(model, messages)
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
            raw2 = await local.generate_or_raise(retry)
        else:
            raw2 = await _cloud_call(model, retry)
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
    """task ∈ judge|extract|typo|structure|function → configured model.

    Returns LLMResult(value=None) when generation or validation fails on
    every available route; callers map that to undetermined.
    """
    settings = get_settings()
    model = settings.llm.models.model_dump()[task]
    key = _cache_key(model, messages)

    cached = _get_cache().get(key)
    if cached is not None:
        _count(cached.get("route", "cloud"))
        try:
            value = schema.model_validate(cached["value"])
        except (ValidationError, KeyError):
            value = None
        return LLMResult(value=value, route=cached.get("route", "cloud"), cached=True)

    order = route_order(task, settings) if route == "auto" else [route]
    last_error: Exception | None = None
    for r in order:
        try:
            value, _raw = await _attempt(schema, model, messages, r)
        except Exception as e:  # noqa: BLE001 — route failure -> next route
            log.warning("llm %s route failed for task %s: %s", r, task, e)
            last_error = e
            continue
        _count(r)
        if value is not None:
            _get_cache().set(key, {"route": r, "value": value.model_dump()})
            return LLMResult(value=value, route=r)
        # generated output failed validation -> try the next route too

    log.warning("all routes failed for task %s: %s", task, last_error)
    return LLMResult(value=None, route=order[-1])
