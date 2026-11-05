"""OpenVINO backends without OpenVINO: device fallback and the local
branches of embed / rerank / local, with the pipelines faked."""

import asyncio

import numpy as np
import pytest

from citecheck.config import LocalSettings, get_settings
from citecheck.llm import embed as embed_mod
from citecheck.llm import local, ov
from citecheck.llm import rerank as rerank_mod
from citecheck.llm.router import route_order


def test_device_order_keeps_config_order_and_matches_gpu_index():
    present = ["CPU", "GPU.0", "GPU.1", "NPU"]
    assert ov.device_order("NPU,GPU,CPU", present) == ["NPU", "GPU.0", "CPU"]
    assert ov.device_order("gpu, cpu", ["CPU"]) == ["CPU"]
    assert ov.device_order("NPU", ["CPU"]) == []


def test_compile_first_falls_back_and_reports_every_error():
    tried = []

    def build(dev):
        tried.append(dev)
        if dev != "CPU":
            raise RuntimeError(f"{dev} cannot compile\nstack")
        return "pipe"

    obj, dev = ov.compile_first("NPU,GPU,CPU", build, ["CPU", "GPU", "NPU"])
    assert (obj, dev) == ("pipe", "CPU") and tried == ["NPU", "GPU", "CPU"]
    with pytest.raises(RuntimeError) as e:
        ov.compile_first("NPU,GPU", build, ["CPU", "GPU", "NPU"])
    assert "NPU: NPU cannot compile" in str(e.value) and "stack" not in str(e.value)
    with pytest.raises(RuntimeError, match="没有可用的设备"):
        ov.compile_first("NPU", build, ["CPU"])


def test_strip_think_and_cache_dir(tmp_path):
    assert ov.strip_think('<think>\n{"a":1}\n</think>\n{"b": 2}') == '\n{"b": 2}'
    assert ov.strip_think('{"b": 2}') == '{"b": 2}'
    assert ov.cache_dir(str(tmp_path)) == tmp_path


def test_reranker_formats_qwen3_pairs():
    rr = ov.Reranker.__new__(ov.Reranker)
    rr.qwen3 = True
    q, ds = rr.format("claim", ["doc"])
    assert q.startswith("<|im_start|>system") and q.endswith("<Query>: claim\n")
    assert ds == ["<Document>: doc<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"]
    rr.qwen3 = False
    assert rr.format("claim", ["doc"]) == ("claim", ["doc"])


class _FakeEmbedder:
    device = "NPU"

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        v = np.array([[float(len(t)), 1.0] for t in texts], dtype=np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def _local_embed(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setenv("CITECHECK_EMBED", "1")
    monkeypatch.setattr(s.llm.embedding, "enabled", True)
    monkeypatch.setattr(s.llm.embedding, "backend", "openvino")
    monkeypatch.setattr(s.llm.embedding, "local_model", str(tmp_path / "Qwen3-Embedding-0.6B-int8-ov"))
    monkeypatch.setattr(s, "embedding_api_key", None)
    monkeypatch.setattr(embed_mod, "_cache", None)
    monkeypatch.setattr(embed_mod, "_down_until", 0.0)
    monkeypatch.setattr(embed_mod, "_local_error", None)
    fake = _FakeEmbedder()
    monkeypatch.setattr(embed_mod, "_local", fake)
    return fake


def test_local_embedding_needs_no_key_and_never_posts(monkeypatch, tmp_path):
    fake = _local_embed(monkeypatch, tmp_path)

    def no_post(*a, **k):
        raise AssertionError("local embeddings must not call the API")

    monkeypatch.setattr(embed_mod.httpx, "post", no_post)
    assert embed_mod.enabled()
    a = embed_mod.embed(["ab", "abcd"])
    b = embed_mod.embed(["abcd", "ab"])
    assert len(fake.calls) == 1 and np.allclose(a[::-1], b)
    embed_mod.embed(["ab"], query=True)
    assert fake.calls[1][0].startswith("Instruct:")
    assert embed_mod.model_id() == "ov:Qwen3-Embedding-0.6B-int8-ov"
    assert embed_mod.status()["device"] == "NPU"


def test_local_embedding_build_failure_switches_to_bm25(monkeypatch, tmp_path):
    _local_embed(monkeypatch, tmp_path)
    monkeypatch.setattr(embed_mod, "_local", None)

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no device")

    monkeypatch.setattr(ov, "Embedder", Boom)
    assert embed_mod.embed(["x"]) is None
    assert not embed_mod.enabled() and "no device" in embed_mod.status()["error"]


def test_local_rerank_scores_in_input_order(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setenv("CITECHECK_RERANK", "1")
    monkeypatch.setattr(s.llm.rerank, "enabled", True)
    monkeypatch.setattr(s.llm.rerank, "backend", "openvino")
    monkeypatch.setattr(s.llm.rerank, "local_model", str(tmp_path / "rr"))
    monkeypatch.setattr(s, "rerank_api_key", None)
    monkeypatch.setattr(rerank_mod, "_cache", None)
    monkeypatch.setattr(rerank_mod, "_down_until", 0.0)
    monkeypatch.setattr(rerank_mod, "_local_error", None)

    class FakeRR:
        device = "GPU.0"
        n = 0

        def rerank(self, q, docs):
            FakeRR.n += 1
            return [0.1 * len(d) for d in docs]

    monkeypatch.setattr(rerank_mod, "_local", FakeRR())
    monkeypatch.setattr(rerank_mod.httpx, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no API")))
    assert rerank_mod.enabled()
    assert rerank_mod.rerank("q", ["a", "abc"]) == pytest.approx([0.1, 0.3])
    assert rerank_mod.rerank("q", ["a", "abc"]) == pytest.approx([0.1, 0.3])
    assert FakeRR.n == 1  # second call is a cache hit


def test_openvino_engine_selected_and_generates(monkeypatch):
    class FakeGen:
        device = "NPU"

        def __init__(self, *a):
            self.args = a

        def generate(self, messages, max_tokens):
            return '{"claims": []}', {"prompt": 12, "completion": 5}

    monkeypatch.setattr(ov, "Generator", FakeGen)
    cfg = LocalSettings(enabled=True, engine="openvino", model="/models/qwen3")
    eng = local.OpenVINOEngine(cfg)
    assert eng.available and eng.device == "NPU" and eng.provider == "openvino-local"
    out = asyncio.run(eng.generate_json([{"role": "user", "content": "x"}]))
    assert out == '{"claims": []}' and eng._last_usage == {"prompt": 12, "completion": 5}


def test_openvino_engine_load_failure_is_reported(monkeypatch):
    def boom(*a):
        raise RuntimeError("模型目录不存在")

    monkeypatch.setattr(ov, "Generator", boom)
    eng = local.OpenVINOEngine(LocalSettings(enabled=True, engine="openvino", model="x"))
    assert not eng.available and "模型目录不存在" in eng.unavailable_reason


def test_openvino_engine_micro_batches_concurrent_requests(monkeypatch):
    class FakeBatch:
        device = "GPU"
        batches = []

        def __init__(self, *a, **k):
            pass

        def generate_batch(self, batch):
            FakeBatch.batches.append(len(batch))
            return [(f'{{"ok": {i}}}', {"prompt": 1, "completion": 1})
                    for i in range(len(batch))]

    class FakeBatchWithPrompt(FakeBatch):
        def prompt(self, messages):
            return "p"

    monkeypatch.setattr(ov, "BatchGenerator", FakeBatchWithPrompt)
    cfg = LocalSettings(enabled=True, engine="openvino", model="x",
                        batching=True, batch_wait_ms=50, timeout=5)
    eng = local.OpenVINOEngine(cfg)

    async def run():
        return await asyncio.gather(*[
            eng.generate_json([{"role": "user", "content": str(i)}], 8)
            for i in range(10)])

    out = asyncio.run(run())
    assert all(o is not None for o in out)
    assert sum(FakeBatch.batches) == 10
    assert max(FakeBatch.batches) >= 2  # requests were grouped, not serialized


def test_batch_result_failure_does_not_poison_the_batch(monkeypatch):
    class FakeBatch:
        device = "GPU"

        def __init__(self, *a, **k):
            pass

        def generate_batch(self, batch):
            return [('{"ok": true}' if i % 2 == 0 else "not json", {})
                    for i in range(len(batch))]

    monkeypatch.setattr(ov, "BatchGenerator", FakeBatch)
    cfg = LocalSettings(enabled=True, engine="openvino", model="x",
                        batching=True, batch_wait_ms=20, timeout=5)
    eng = local.OpenVINOEngine(cfg)

    async def run():
        return await asyncio.gather(*[
            eng.generate_json([{"role": "user", "content": str(i)}], 8)
            for i in range(6)])

    out = asyncio.run(run())
    assert sum(o is not None for o in out) == 3
    assert all(o == '{"ok": true}' for o in out if o is not None)


def test_batch_timeout_returns_none(monkeypatch):
    import time as _time

    class SlowBatch:
        device = "GPU"

        def __init__(self, *a, **k):
            pass

        def generate_batch(self, batch):
            _time.sleep(0.3)
            return [('{"ok": true}', {}) for _ in batch]

    monkeypatch.setattr(ov, "BatchGenerator", SlowBatch)
    cfg = LocalSettings(enabled=True, engine="openvino", model="x",
                        batching=True, batch_wait_ms=5, timeout=0.05)
    eng = local.OpenVINOEngine(cfg)
    out = asyncio.run(eng.generate_json([{"role": "user", "content": "x"}], 8))
    assert out is None


def test_route_order_uses_local_tasks(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s.llm.local, "enabled", True)
    monkeypatch.setattr(s.llm.local, "tasks", ["extract", "judge"])
    assert route_order("extract", s) == ["local", "cloud"]
    assert route_order("judge", s) == ["local", "cloud"]
    assert route_order("typo", s) == ["cloud"]

    monkeypatch.setattr(s.llm.local, "enabled", False)
    assert route_order("extract", s) == ["cloud"]
