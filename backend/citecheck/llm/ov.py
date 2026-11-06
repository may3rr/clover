"""OpenVINO GenAI backends for Intel machines (AGENTS §5.2: model calls
live in llm/).

Three on-device pipelines, each loaded from an OpenVINO IR directory:

- ``Embedder``: Qwen3-Embedding for excerpt retrieval (``llm/embed.py``)
- ``Reranker``: Qwen3-Reranker over the fused candidates (``llm/rerank.py``)
- ``Generator``: a Qwen3 chat model for ``extract`` (``llm/local.py``)

Devices are tried in the configured order (default NPU, GPU, CPU); the
first one that compiles the model is kept and reported, so the settings
page can say where the model actually runs. NPU compiles static shapes:
embeddings pad every window to ``max_length`` and run one window per
request, chat prompts are capped at ``max_prompt_len``. Compiled blobs go
to a cache folder so the second start skips compilation.

``openvino_genai`` is imported lazily: it is an optional dependency
(``pip install -e .[intel]``) and the Mac build never loads it.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import numpy as np

log = logging.getLogger(__name__)

T = TypeVar("T")

# Qwen3-Reranker's chat framing (model card); the pipeline adds nothing
_RERANK_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements "
    "based on the Query and the Instruct provided. Note that the answer can "
    'only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
_RERANK_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
RERANK_TASK = ("Given a claim from a survey paper, retrieve the passage of "
               "the cited paper that supports or contradicts it")


def cache_dir(configured: str = "") -> Path:
    """Folder for OpenVINO's compiled-model cache."""
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "citecheck" / "openvino"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "citecheck" / "openvino"
    return Path.home() / ".cache" / "citecheck" / "openvino"


def available_devices() -> list[str]:
    """Devices OpenVINO sees on this machine, e.g. ['CPU', 'GPU', 'NPU']."""
    import openvino as ov

    return list(ov.Core().available_devices)


def device_order(spec: str, present: list[str]) -> list[str]:
    """The configured order restricted to devices that are present.
    ``GPU`` matches ``GPU.0`` / ``GPU.1`` (the first one is taken)."""
    out: list[str] = []
    for want in (d.strip().upper() for d in spec.split(",")):
        if not want:
            continue
        for have in present:
            if (have == want or have.split(".")[0] == want) and have not in out:
                out.append(have)
                break
    return out


def compile_first(spec: str, build: Callable[[str], T],
                  present: list[str] | None = None) -> tuple[T, str]:
    """Build on the first device in ``spec`` that works. Raises with every
    device's error when none does."""
    present = available_devices() if present is None else present
    order = device_order(spec, present)
    if not order:
        raise RuntimeError(f"没有可用的设备：配置 {spec}，本机 {','.join(present) or '无'}")
    errors = []
    for dev in order:
        try:
            obj = build(dev)
            log.info("openvino: compiled on %s", dev)
            return obj, dev
        except Exception as e:  # noqa: BLE001 — try the next device
            log.warning("openvino: %s failed: %s", dev, e)
            errors.append(f"{dev}: {str(e).splitlines()[0][:200] if str(e) else type(e).__name__}")
    raise RuntimeError("；".join(errors))


def _props(cache: str, extra: dict | None = None) -> dict:
    d = cache_dir(cache)
    d.mkdir(parents=True, exist_ok=True)
    return {"CACHE_DIR": str(d), **(extra or {})}


def _check_dir(path: str) -> Path:
    p = Path(path).expanduser()
    if not path or not p.is_dir():
        raise RuntimeError(f"模型目录不存在：{path or '（未配置）'}")
    return p


def model_type(path: str | Path) -> str:
    try:
        cfg = json.loads((Path(path) / "config.json").read_text(encoding="utf-8"))
        return str(cfg.get("model_type", ""))
    except (OSError, ValueError):
        return ""


class Embedder:
    """Last-token pooled, L2-normalized embeddings (Qwen3-Embedding)."""

    def __init__(self, path: str, devices: str, max_length: int = 512,
                 cache: str = "", present: list[str] | None = None):
        import openvino_genai as g

        p = _check_dir(path)
        self.max_length = max_length

        def build(dev: str):
            cfg = g.TextEmbeddingPipeline.Config()
            cfg.pooling_type = g.TextEmbeddingPipeline.PoolingType.LAST_TOKEN
            cfg.normalize = True
            cfg.padding_side = "left"
            cfg.max_length = max_length
            if dev == "NPU":
                # left padding with last-token pooling needs a fixed shape
                cfg.batch_size = 1
                cfg.pad_to_max_length = True
            return g.TextEmbeddingPipeline(str(p), dev, cfg, **_props(cache))

        self.pipe, self.device = compile_first(devices, build, present)
        self.batch = 1 if self.device == "NPU" else 16
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> np.ndarray:
        rows: list[np.ndarray] = []
        with self._lock:  # one infer request per pipeline
            for i in range(0, len(texts), self.batch):
                chunk = list(texts[i:i + self.batch])
                out = np.asarray(self.pipe.embed_documents(chunk), dtype=np.float32)
                rows.append(out.reshape(len(chunk), -1))
        vecs = np.concatenate(rows) if rows else np.zeros((0, 0), np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.where(norms == 0, 1.0, norms)


class Reranker:
    """Cross-encoder relevance in [0, 1], in the order of the input docs."""

    def __init__(self, path: str, devices: str, max_length: int = 512,
                 cache: str = "", present: list[str] | None = None):
        import openvino_genai as g

        p = _check_dir(path)
        self.qwen3 = model_type(p) == "qwen3"

        def build(dev: str):
            cfg = g.TextRerankPipeline.Config()
            cfg.top_n = 1 << 20  # every score, not just the best three
            cfg.max_length = max_length
            if dev == "NPU":
                cfg.padding_side = "left"
            return g.TextRerankPipeline(str(p), dev, cfg, **_props(cache))

        self.pipe, self.device = compile_first(devices, build, present)
        self._lock = threading.Lock()

    def format(self, query: str, docs: list[str]) -> tuple[str, list[str]]:
        if not self.qwen3:
            return query, docs
        q = f"{_RERANK_PREFIX}<Instruct>: {RERANK_TASK}\n<Query>: {query}\n"
        return q, [f"<Document>: {d}{_RERANK_SUFFIX}" for d in docs]

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        q, ds = self.format(query, docs)
        with self._lock:
            pairs = self.pipe.rerank(q, ds)
        scores = [0.0] * len(docs)
        for idx, score in pairs:
            scores[int(idx)] = float(score)
        return scores


def strip_think(text: str) -> str:
    """Drop a Qwen3 <think>…</think> block if the model emitted one."""
    end = text.find("</think>")
    return text[end + len("</think>"):] if end >= 0 else text


class Generator:
    """Greedy chat generation with thinking turned off."""

    def __init__(self, path: str, devices: str, max_prompt_len: int = 1024,
                 min_response_len: int = 256, cache: str = "",
                 present: list[str] | None = None):
        import openvino_genai as g

        self._g = g
        p = _check_dir(path)
        self.max_prompt_len = max_prompt_len

        def build(dev: str):
            extra = {}
            if dev == "NPU":
                extra = {"MAX_PROMPT_LEN": max_prompt_len,
                         "MIN_RESPONSE_LEN": min_response_len}
            return g.LLMPipeline(str(p), dev, **_props(cache, extra))

        self.pipe, self.device = compile_first(devices, build, present)
        self.tokenizer = self.pipe.get_tokenizer()

    def generate(self, messages: list[dict], max_tokens: int) -> tuple[str, dict[str, int]]:
        g = self._g
        history = g.ChatHistory(messages)
        history.set_extra_context({"enable_thinking": False})
        cfg = g.GenerationConfig()
        cfg.max_new_tokens = max_tokens
        cfg.do_sample = False
        res = self.pipe.generate(history, cfg)
        text = res.texts[0] if hasattr(res, "texts") else str(res)
        usage = {}
        try:
            pm = res.perf_metrics
            usage = {"prompt": int(pm.get_num_input_tokens()),
                     "completion": int(pm.get_num_generated_tokens())}
        except Exception:  # noqa: BLE001 — token counts are best-effort
            pass
        return strip_think(text), usage


class BatchGenerator:
    """Continuous-batching chat generation for the local engine.

    One ``ContinuousBatchingPipeline`` serves a whole micro-batch. Requests
    are grouped by the caller (``OpenVINOEngine`` waits up to 30 ms or
    ``max_num_seqs``). Thinking is disabled through the chat template; a
    closed ``<think>`` block is appended when a template ignores the flag.
    """

    def __init__(self, path: str, devices: str = "GPU",
                 max_prompt_len: int = 2048, min_response_len: int = 256,
                 cache: str = "", max_num_seqs: int = 16,
                 cache_size: float = 6.0, max_num_batched_tokens: int = 32768,
                 enable_prefix_caching: bool = True,
                 present: list[str] | None = None):
        import openvino_genai as g

        p = _check_dir(path)
        self._g = g
        sched = g.SchedulerConfig()
        for attr, value in (("max_num_seqs", max_num_seqs),
                            ("max_num_batched_tokens", max_num_batched_tokens),
                            ("cache_size", cache_size),
                            ("enable_prefix_caching", enable_prefix_caching)):
            try:
                setattr(sched, attr, value)
            except Exception:  # noqa: BLE001 — older runtimes lack some knobs
                pass

        def build(dev: str):
            extra = {}
            if dev == "NPU":
                extra = {"MAX_PROMPT_LEN": max_prompt_len,
                         "MIN_RESPONSE_LEN": min_response_len}
            return g.ContinuousBatchingPipeline(
                str(p), sched, dev, _props(cache, extra))

        self.pipe, self.device = compile_first(devices, build, present)
        self.tokenizer = g.Tokenizer(str(p))
        self._lock = threading.Lock()

    def prompt(self, messages: list[dict]) -> str:
        prompt = self.tokenizer.apply_chat_template(
            messages, True, extra_context={"enable_thinking": False})
        if not prompt.rstrip().endswith("</think>"):
            # templates that ignore enable_thinking: force a closed block
            prompt += "<think>\n\n</think>\n\n"
        return prompt

    def generate_batch(
        self, batch: list[tuple[list[dict], int]]
    ) -> list[tuple[str, dict]]:
        """Run one micro-batch; returns (text, usage) per request."""
        g = self._g
        prompts = [self.prompt(m) for m, _ in batch]
        configs = []
        for _, max_tokens in batch:
            cfg = g.GenerationConfig()
            cfg.max_new_tokens = max_tokens
            cfg.do_sample = False
            configs.append(cfg)
        with self._lock:
            results = self.pipe.generate(prompts, configs)
        out: list[tuple[str, dict]] = []
        for res, prompt in zip(results, prompts):
            token_ids: list[int] = []
            text = ""
            try:
                ids = res.get_generation_ids()
                if ids:
                    first = ids[0]
                    token_ids = [first] if isinstance(first, int) else list(first)
                    text = self.tokenizer.decode(token_ids)
            except Exception:  # noqa: BLE001 — fall back to a text attribute
                try:
                    text = res.texts[0]
                except Exception:
                    text = str(res)
            text = strip_think(text)
            usage: dict[str, int] = {}
            try:
                usage = {
                    "prompt": int(self.tokenizer.encode(prompt).input_ids.shape[-1]),
                    "completion": len(token_ids),
                }
            except Exception:  # noqa: BLE001 — token counts are best-effort
                pass
            out.append((text, usage))
        return out
