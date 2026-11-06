"""Unified LLM access for citecheck (AGENTS §5.2).

Business code calls ``chat_json(task, messages, Schema)`` and gets back a
pydantic-validated value; routing (local vs cloud), caching, retries and
call counting live here. No business module imports openai/mlx directly.
"""

from __future__ import annotations

import asyncio
import time
import heapq
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from ..cache import Cache, make_key
from ..config import get_settings
from . import local, privacy, sendlog
from .router import route_order

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
Route = Literal["local", "cloud"]

_cache: Cache | None = None
_cloud_client: AsyncOpenAI | None = None
_cloud_sem: "PrioritySemaphore | None" = None
_local_sem: "PrioritySemaphore | None" = None
_local_loop: asyncio.AbstractEventLoop | None = None

# Who goes first when every cloud slot is busy (lower = sooner). Only
# reference structuring jumps the queue: it gates authenticity,
# distribution and claim pairing. The layers' own calls share one level
# (FIFO) — ranking typo checks below judging starved the norms layer
# until support finished and made it the new critical path. The overview
# critic runs last anyway.
_PRIORITY = {
    "structure": 0, "bibguess": 0,
    "extract": 1, "judge": 1, "review": 1, "review_fallback": 1,
    "function": 1, "typo": 1,
    "profile": 2, "overview": 2,
}


class PrioritySemaphore:
    """Bounded concurrency whose waiters are released by priority (FIFO
    within one priority). A released slot is handed straight to the next
    waiter, so a late high-priority call never starves behind a queue of
    low-priority ones."""

    def __init__(self, value: int):
        self._value = value
        self._waiters: list[tuple[int, int, asyncio.Future]] = []
        self._seq = 0

    async def acquire(self, priority: int = 2) -> None:
        if self._value > 0 and not any(
                not f.done() for _p, _s, f in self._waiters):
            self._value -= 1
            return
        fut = asyncio.get_running_loop().create_future()
        self._seq += 1
        heapq.heappush(self._waiters, (priority, self._seq, fut))
        try:
            await fut
        except asyncio.CancelledError:
            # the slot was handed over just before the cancel landed
            if fut.done() and not fut.cancelled():
                self.release()
            raise

    def release(self) -> None:
        while self._waiters:
            _p, _s, fut = heapq.heappop(self._waiters)
            if not fut.done():
                fut.set_result(None)
                return
        self._value += 1

    def slot(self, priority: int = 2) -> "_Slot":
        return _Slot(self, priority)


class _Slot:
    def __init__(self, sem: PrioritySemaphore, priority: int):
        self._sem, self._priority = sem, priority

    async def __aenter__(self) -> None:
        await self._sem.acquire(self._priority)

    async def __aexit__(self, *exc: object) -> None:
        self._sem.release()


class LLMStats:
    """Per-job call counters; opened by the pipeline via stats_scope()."""

    def __init__(self) -> None:
        self.local = 0
        self.cloud = 0
        # model -> {"prompt": tokens, "completion": tokens}; real API calls
        # only — cache hits are counted in local/cloud but use no tokens
        self.usage: dict[str, dict[str, int]] = {}
        # task -> calls privacy mode skipped (no local model; nothing sent)
        self.skipped: dict[str, int] = {}


_current_stats: ContextVar[LLMStats | None] = ContextVar("llm_stats", default=None)
_current_doc = sendlog.current_doc


class doc_scope:
    """Stamp llm_usage rows with the document being processed, so usage
    can be aggregated per paper, and with the run (the report's send list
    reads that run's rows). Opened by the pipeline per job."""

    def __init__(self, doc: str, run: str | None = None) -> None:
        self.doc = doc
        self.run = run
        self._tokens: tuple = ()

    def __enter__(self) -> None:
        self._tokens = (sendlog.current_doc.set(self.doc),
                        sendlog.current_run.set(self.run))
        return None

    def __exit__(self, *exc: object) -> None:
        sendlog.current_doc.reset(self._tokens[0])
        sendlog.current_run.reset(self._tokens[1])


def note_skipped(task: str) -> None:
    """Count a call privacy mode did not make (shown in the report)."""
    s = _current_stats.get()
    if s is not None:
        s.skipped[task] = s.skipped.get(task, 0) + 1


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
        return local.provider()
    host = urlparse(get_settings().llm.cloud.base_url).hostname or "cloud"
    # Qwen endpoints (official DashScope or a qianwen-branded gateway) all
    # bill as Alibaba Bailian in the usage view
    if any(k in host for k in ("dashscope", "aliyun", "qianwen")):
        return "dashscope"
    return host


def _model_for(route: str, task_model: str) -> str:
    if route == "local":
        return get_settings().llm.local.model
    return task_model


def _log_usage(route: str, task: str, model: str, prompt: int, completion: int,
               cached: bool = False, chars: int = 0,
               parts: list[dict] | None = None) -> None:
    """Persist one call (or cache hit) into the llm_usage table, with the
    characters and content parts it sent (send list). Never allowed to
    break the request path."""
    try:
        cache = _get_cache()
    except Exception as e:  # noqa: BLE001
        log.debug("usage log open failed: %s", e)
        return
    sendlog.record(cache, provider=_provider_for(route), model=model,
                   task=task, route=route, prompt=prompt,
                   completion=completion, cached=cached, chars=chars,
                   parts=parts)


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


_cloud_loop: asyncio.AbstractEventLoop | None = None


def _get_cloud() -> tuple[AsyncOpenAI, PrioritySemaphore]:
    global _cloud_client, _cloud_sem, _cloud_loop
    settings = get_settings()
    loop = asyncio.get_running_loop()
    # the client's connection pool belongs to one event loop: a new loop
    # (another asyncio.run in a batch script) gets a fresh client
    if _cloud_client is None or _cloud_loop is not loop:
        _cloud_loop = loop
        _cloud_client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.llm.cloud.base_url,
            timeout=settings.llm.cloud.timeout,
        )
        _cloud_sem = PrioritySemaphore(settings.llm.cloud.max_concurrency)
    return _cloud_client, _cloud_sem  # type: ignore[return-value]


def _get_local_sem() -> PrioritySemaphore:
    """Local concurrency has its own limit; it never shares the cloud
    semaphore (a local NPU/GPU queue and a remote API queue are different
    resources)."""
    global _local_sem, _local_loop
    settings = get_settings()
    loop = asyncio.get_running_loop()
    if _local_sem is None or _local_loop is not loop:
        _local_loop = loop
        _local_sem = PrioritySemaphore(settings.llm.local.effective_concurrency())
    return _local_sem


def _cache_key(model: str, messages: list[dict]) -> str:
    # cache_version is part of the key: bump it in config.toml to
    # invalidate every cached verdict after a model upgrade / prompt fix
    return make_key(
        model, get_settings().cache_version,
        json.dumps(messages, ensure_ascii=False, sort_keys=True))


@dataclass
class LLMResult:
    value: Any  # validated pydantic instance, or None on failure
    route: Route
    cached: bool = False
    error: str | None = None  # compact error description when value is None
    # privacy mode had no allowed route: nothing was generated or sent
    skipped: bool = False


def _ensure_json_word(messages: list[dict]) -> list[dict]:
    """DashScope json_object mode requires the string "json" in messages."""
    blob = " ".join(str(m.get("content", "")) for m in messages)
    if "json" in blob.lower():
        return messages
    return [{"role": "system", "content": "只输出 JSON。"}] + messages


def _transient(e: Exception) -> bool:
    """Errors worth waiting out: the network, a timeout, rate limiting or
    a server-side failure. Bad requests and auth errors are not."""
    import openai
    if isinstance(e, (openai.APIConnectionError, openai.APITimeoutError,
                      openai.RateLimitError, openai.InternalServerError)):
        return True
    status = getattr(e, "status_code", None)
    return isinstance(status, int) and status >= 500


# content parts of the chat_json call in flight (send list); a ContextVar
# keeps _cloud_call's signature (tests replace it with 3-argument fakes)
_parts: ContextVar[list[dict] | None] = ContextVar("llm_parts", default=None)


async def _cloud_call(model: str, messages: list[dict], task: str) -> str:
    parts = _parts.get()
    client, sem = _get_cloud()
    settings = get_settings()
    budget = settings.llm.cloud.retry_seconds
    started = time.monotonic()
    delay = 2.0
    while True:
        try:
            async with sem.slot(_PRIORITY.get(task, 2)):
                resp = await client.chat.completions.create(
                    model=model,
                    messages=_ensure_json_word(messages),
                    temperature=settings.llm.temperature,
                    response_format={"type": "json_object"},
                    extra_body={"enable_thinking": False},
                )
            break
        except Exception as e:
            # the request may have reached the provider: it counts as sent
            _log_usage("cloud", task, model, 0, 0,
                       chars=sendlog.message_chars(messages), parts=parts)
            waited = time.monotonic() - started
            if not _transient(e) or waited + delay > budget:
                log.warning("cloud call failed model=%s: %s", model, _err_desc(e))
                raise
            # back off outside the semaphore: a waiting call holds no slot
            log.info("cloud call retry in %.0fs model=%s: %s",
                     delay, model, _err_desc(e))
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
    _record_usage(model, resp.usage)
    _log_usage(
        "cloud", task, model,
        getattr(resp.usage, "prompt_tokens", 0) or 0,
        getattr(resp.usage, "completion_tokens", 0) or 0,
        chars=sendlog.message_chars(messages), parts=parts,
    )
    return resp.choices[0].message.content or ""


async def _local_call(messages: list[dict], task: str) -> str:
    sem = _get_local_sem()
    async with sem.slot(_PRIORITY.get(task, 2)):
        raw = await local.generate_or_raise(messages)  # raises on failure
    usage = local.last_usage() or {}
    _log_usage(
        "local", task, get_settings().llm.local.model,
        usage.get("prompt", 0), usage.get("completion", 0),
        chars=sendlog.message_chars(messages),
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
    parts: list[sendlog.Part] | None = None,
) -> LLMResult:
    """task ∈ judge|review|review_fallback|extract|typo|structure|function
    → configured model.

    ``parts``: the user data in the prompt as (category, text[, key])
    pieces for the send list (llm/sendlog.py); without them the user
    messages count as one piece of the task's usual category.

    Privacy mode (llm/privacy.py) narrows the routes: a private task or a
    call inside ``privacy.local_only`` runs locally or not at all — an
    empty route list returns LLMResult(value=None, skipped=True) without
    sending anything.

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
    order = privacy.allowed_routes(task, order, settings)
    if not order:
        note_skipped(task)
        return LLMResult(value=None, route="local", error="skipped",
                         skipped=True)
    packed = sendlog.pack(parts if parts is not None
                          else sendlog.default_parts(task, messages))
    last_error: Exception | None = None
    for r in order:
        token = _parts.set(packed)
        try:
            value, _raw = await _attempt(schema, model, messages, r, task)
        except Exception as e:  # noqa: BLE001 — route failure -> next route
            log.warning("llm %s route failed for task %s: %s", r, task,
                        _err_desc(e))
            last_error = e
            continue
        finally:
            _parts.reset(token)
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
