"""On-device generation on a single dedicated worker thread.

Two engines behind one interface, picked by ``[llm.local] engine``:
mlx-lm on Apple silicon, OpenVINO GenAI on Intel NPU/GPU/CPU
(``llm/ov.py``). Neither runtime is thread-safe for one model, so all
generation is funnelled through one ThreadPoolExecutor(max_workers=1).
If importing the runtime or loading the model fails, the engine reports
unavailable once and is never retried for the life of the process.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import queue
import threading
import time

log = logging.getLogger(__name__)

_lock = threading.Lock()
_engine: "LocalEngine | None" = None


def _extract_json(text: str) -> str | None:
    """First balanced JSON object in the model output."""
    idx = text.find("{")
    while idx >= 0:
        try:
            obj, end = json.JSONDecoder().raw_decode(text[idx:])
            return text[idx : idx + end]
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)
    return None


class LocalEngine:
    """mlx-lm engine (Apple silicon)."""

    provider = "mlx-local"
    device: str | None = "Apple GPU"

    def __init__(self, model_name: str, hf_endpoint: str | None, timeout: float):
        self.model_name = model_name
        self.timeout = timeout
        self.available = False
        self.unavailable_reason: str | None = None
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="local-llm"
        )
        self._model = None
        self._tokenizer = None
        self._last_usage: dict[str, int] | None = None
        if hf_endpoint:
            os.environ.setdefault("HF_ENDPOINT", hf_endpoint)
        try:
            import mlx_lm  # noqa: F401
        except Exception as e:  # noqa: BLE001
            self.unavailable_reason = f"mlx-lm 不可用: {e}"
            log.warning("local LLM unavailable: %s", e)
            return
        try:
            from mlx_lm import load

            self._model, self._tokenizer = load(model_name)
            self.available = True
        except Exception as e:  # noqa: BLE001
            self.unavailable_reason = f"模型加载失败: {e}"
            log.warning("local LLM model load failed: %s", e)

    def _generate_sync(self, messages: list[dict], max_tokens: int) -> str:
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        from mlx_lm import generate

        try:
            from mlx_lm.sample_utils import make_sampler

            out = generate(
                self._model, self._tokenizer, prompt,
                max_tokens=max_tokens, sampler=make_sampler(temp=0.0),
            )
        except TypeError:
            out = generate(
                self._model, self._tokenizer, prompt,
                max_tokens=max_tokens, temp=0.0,
            )
        out = out if isinstance(out, str) else str(out)
        try:
            self._last_usage = {
                "prompt": len(self._tokenizer.encode(prompt)),
                "completion": len(self._tokenizer.encode(out)),
            }
        except Exception:  # noqa: BLE001 — token counting is best-effort
            self._last_usage = None
        return out

    async def generate_json(
        self, messages: list[dict], max_tokens: int = 1024
    ) -> str | None:
        """Run one generation; returns the first JSON object as text, or
        None on timeout/failure. Never raises."""
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(
            self._executor, self._generate_sync, messages, max_tokens
        )
        try:
            text = await asyncio.wait_for(fut, timeout=self.timeout)
        except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
            log.warning("local generation failed: %s", e)
            return None
        return _extract_json(text)


class OpenVINOEngine(LocalEngine):
    """OpenVINO GenAI engine (Intel NPU → GPU → CPU); ``model`` is the IR
    directory."""

    provider = "openvino-local"

    def __init__(self, settings: "LocalSettings"):  # noqa: F821
        self.model_name = settings.model
        self.timeout = settings.timeout
        self.available = False
        self.unavailable_reason = None
        self.device = None
        self._last_usage = None
        self._gen = None
        self._batcher = None
        self._batch_queue: queue.Queue | None = None
        self._batching = bool(getattr(settings, "batching", False))
        self._config = settings
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="local-llm"
        )
        try:
            from . import ov

            # compile on the worker thread that will run every generation
            if self._batching:
                self._batcher = self._executor.submit(
                    ov.BatchGenerator, settings.model, settings.device,
                    settings.max_prompt_len, settings.min_response_len,
                    settings.ov_cache_dir,
                    settings.batch_max_num_seqs, settings.batch_cache_size,
                    settings.batch_max_num_batched_tokens,
                    settings.batch_prefix_caching,
                ).result()
                self.device = self._batcher.device
                self._batch_queue = queue.Queue()
                threading.Thread(target=self._batch_loop, name="local-batch",
                                 daemon=True).start()
            else:
                self._gen = self._executor.submit(
                    ov.Generator, settings.model, settings.device,
                    settings.max_prompt_len, settings.min_response_len,
                    settings.ov_cache_dir,
                ).result()
                self.device = self._gen.device
            self.available = True
        except Exception as e:  # noqa: BLE001
            self.unavailable_reason = f"OpenVINO 模型加载失败: {e}"
            log.warning("openvino LLM unavailable: %s", e)

    def _generate_sync(self, messages: list[dict], max_tokens: int) -> str:
        assert self._gen is not None
        text, usage = self._gen.generate(messages, max_tokens)
        self._last_usage = usage or None
        return text

    def _batch_loop(self) -> None:
        """Collect queued requests for up to batch_wait_ms (or max_num_seqs)
        and run them through one ContinuousBatchingPipeline call."""
        assert self._batch_queue is not None and self._batcher is not None
        wait_s = max(0.0, float(getattr(self._config, "batch_wait_ms", 30)) / 1000.0)
        max_seqs = max(1, int(getattr(self._config, "batch_max_num_seqs", 16)))
        while True:
            first = self._batch_queue.get()
            batch = [first]
            deadline = time.monotonic() + wait_s
            while len(batch) < max_seqs:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    batch.append(self._batch_queue.get(timeout=remaining))
                except queue.Empty:
                    break
            items = [(messages, max_tokens)
                     for _loop, _fut, messages, max_tokens in batch]
            try:
                results = self._batcher.generate_batch(items)
            except Exception as e:  # noqa: BLE001 — fail this batch only
                for loop, fut, _m, _t in batch:
                    self._deliver(loop, self._resolve_error, fut, e)
                continue
            for (loop, fut, _m, _t), (text, usage) in zip(batch, results):
                self._last_usage = usage or None
                self._deliver(loop, self._resolve_ok, fut, text)

    @staticmethod
    def _deliver(loop: asyncio.AbstractEventLoop, fn, *args) -> None:
        """Set a future result from the worker thread; the event loop may
        already be closed when the caller timed out and the script exited."""
        if loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:  # loop closed between the check and the call
            pass

    @staticmethod
    def _resolve_ok(fut: asyncio.Future, text: str) -> None:
        if not fut.done():
            fut.set_result(text)

    @staticmethod
    def _resolve_error(fut: asyncio.Future, exc: Exception) -> None:
        if not fut.done():
            fut.set_exception(exc)

    async def generate_json(
        self, messages: list[dict], max_tokens: int = 1024
    ) -> str | None:
        """Queue one request for the micro-batcher (or run it serially when
        batching is off). Never raises; returns None on timeout/failure."""
        if not self._batching or self._batch_queue is None:
            return await super().generate_json(messages, max_tokens)
        if not self.available:
            return None
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._batch_queue.put((loop, fut, messages, max_tokens))
        try:
            text = await asyncio.wait_for(fut, timeout=self.timeout)
        except Exception as e:  # noqa: BLE001 — timeout or batch failure
            log.warning("local batched generation failed: %s", e)
            return None
        return _extract_json(text) if text else None


async def generate_or_raise(
    messages: list[dict], max_tokens: int = 1024
) -> str:
    """Used by the router: raises so the caller can fall back to cloud."""
    engine = get_engine()
    if engine is None:
        raise RuntimeError("local model disabled")
    if not engine.available:
        raise RuntimeError(engine.unavailable_reason or "local model unavailable")
    out = await engine.generate_json(messages, max_tokens)
    if out is None:
        raise RuntimeError("local generation failed or timed out")
    return out


def last_usage() -> dict[str, int] | None:
    """Token counts from the most recent local generation, for the usage log."""
    e = _engine
    return e._last_usage if e is not None else None


def get_engine() -> LocalEngine | None:
    """Process-wide engine, built lazily; None when disabled."""
    global _engine
    from ..config import get_settings

    settings = get_settings()
    if not settings.llm.local.enabled:
        return None
    cfg = settings.llm.local
    with _lock:
        if _engine is None:
            if cfg.engine == "openvino":
                _engine = OpenVINOEngine(cfg)
            else:
                _engine = LocalEngine(cfg.model, cfg.hf_endpoint, cfg.timeout)
    return _engine


def provider() -> str:
    """Usage-log provider name of the configured engine."""
    from ..config import get_settings

    e = _engine
    if e is not None:
        return e.provider
    return ("openvino-local" if get_settings().llm.local.engine == "openvino"
            else "mlx-local")
