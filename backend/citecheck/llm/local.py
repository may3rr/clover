"""Local mlx-lm inference on a single dedicated worker thread.

mlx is not thread-safe, so all generation is funnelled through one
ThreadPoolExecutor(max_workers=1). If importing mlx-lm or loading the
model fails, the engine reports unavailable once and is never retried
for the life of the process.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import threading
from typing import Any

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
    def __init__(self, model_name: str, hf_endpoint: str | None, timeout: float):
        self.model_name = model_name
        self.timeout = timeout
        self.available = False
        self.unavailable_reason: str | None = None
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mlx"
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
    with _lock:
        if _engine is None:
            _engine = LocalEngine(
                settings.llm.local.model,
                settings.llm.local.hf_endpoint,
                settings.llm.local.timeout,
            )
    return _engine
