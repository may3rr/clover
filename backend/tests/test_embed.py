import httpx
import numpy as np

from citecheck.config import get_settings
from citecheck.llm import embed as embed_mod
from citecheck.support import sources


def _on(monkeypatch):
    s = get_settings()
    monkeypatch.setenv("CITECHECK_EMBED", "1")
    monkeypatch.setattr(s.llm.embedding, "enabled", True)
    monkeypatch.setattr(s, "embedding_api_key", "test-key")
    monkeypatch.setattr(embed_mod, "_cache", None)
    monkeypatch.setattr(embed_mod, "_down_until", 0.0)


def test_embed_caches_vectors(monkeypatch):
    _on(monkeypatch)
    sent = []

    def fake_post(url, headers, json, timeout):
        sent.append(list(json["input"]))
        data = [{"index": i, "embedding": [float(len(t)), 1.0]}
                for i, t in enumerate(json["input"])]
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 3}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(embed_mod.httpx, "post", fake_post)
    a = embed_mod.embed(["ab", "abcd"])
    b = embed_mod.embed(["abcd", "ab"])
    assert len(sent) == 1
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-3)
    assert np.allclose(a[::-1], b)
    # queries carry the instruction, so they are separate cache entries
    embed_mod.embed(["ab"], query=True)
    assert len(sent) == 2 and sent[1][0].startswith("Instruct:")


def test_embed_failure_falls_back(monkeypatch):
    _on(monkeypatch)

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(embed_mod.httpx, "post", boom)
    monkeypatch.setattr(embed_mod.time, "sleep", lambda s: None)
    assert embed_mod.embed(["x"]) is None
    # disabled by default in tests
    monkeypatch.setenv("CITECHECK_EMBED", "0")
    assert embed_mod.embed(["x"]) is None


def test_excerpt_fuses_dense_ranking(monkeypatch):
    """BM25 alone takes the window that repeats the query word; when the
    embedding ranks another matching window first and that one last, the
    fused excerpt takes the other."""
    filler = "Delta epsilon zeta. " * 12
    body = (filler + "The taxonomy taxonomy section is long. " + filler
            + "The taxonomy holds about 150 named entity types. " + filler)

    def fake_dense(windows, query):
        return np.array([1.0 if "150" in w else -1.0 if "taxonomy taxonomy" in w else 0.0
                         for w in windows])

    plain = sources._bm25_excerpt(body, "taxonomy", 200, max_parts=1)
    monkeypatch.setattr(sources, "_dense_scores", fake_dense)
    fused = sources._bm25_excerpt(body, "taxonomy", 200, max_parts=1)
    assert "taxonomy taxonomy" in plain and "150" not in plain
    assert "150" in fused


def test_rerank_reorders_fused_candidates(monkeypatch):
    """The cross-encoder's order decides among the top fused candidates."""
    from citecheck.llm import rerank as rerank_mod

    filler = "Delta epsilon zeta. " * 12
    body = (filler + "The taxonomy taxonomy section is long. " + filler
            + "The taxonomy holds about 150 named entity types. " + filler)

    def fake_dense(windows, query):
        return np.array([0.5 if "taxonomy" in w else 0.0 for w in windows])

    def fake_rerank(query, docs):
        return [1.0 if "150" in d else 0.1 for d in docs]

    monkeypatch.setattr(sources, "_dense_scores", fake_dense)
    monkeypatch.setattr(rerank_mod, "rerank", fake_rerank)
    out = sources._bm25_excerpt(body, "taxonomy", 200, max_parts=1)
    assert "150" in out
    # reranker unavailable: the fused order stands
    monkeypatch.setattr(rerank_mod, "rerank", lambda q, d: None)
    out = sources._bm25_excerpt(body, "taxonomy", 200, max_parts=1)
    assert "taxonomy taxonomy" in out


def test_embed_dashscope_compatible_request(monkeypatch):
    _on(monkeypatch)
    cfg = get_settings().llm.embedding
    monkeypatch.setattr(cfg, "base_url",
                        "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(cfg, "model", "test-embedding")
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, json=json)
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [3.0, 4.0]}],
                  "usage": {"total_tokens": 2}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(embed_mod.httpx, "post", fake_post)
    out = embed_mod.embed(["claim"])
    assert sent["url"].endswith("/compatible-mode/v1/embeddings")
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["json"] == {"model": "test-embedding", "input": ["claim"]}
    assert np.allclose(out, [[0.6, 0.8]], atol=1e-3)


def _rerank_on(monkeypatch, api_format):
    from citecheck.llm import rerank as rerank_mod

    s = get_settings()
    monkeypatch.setenv("CITECHECK_RERANK", "1")
    monkeypatch.setattr(s.llm.rerank, "enabled", True)
    monkeypatch.setattr(s.llm.rerank, "api_format", api_format)
    monkeypatch.setattr(s.llm.rerank, "model", f"test-{api_format}")
    monkeypatch.setattr(s, "rerank_api_key", "test-key")
    monkeypatch.setattr(rerank_mod, "_cache", None)
    monkeypatch.setattr(rerank_mod, "_down_until", 0.0)
    return rerank_mod, s.llm.rerank


def test_rerank_dashscope_native_request(monkeypatch):
    rerank_mod, cfg = _rerank_on(monkeypatch, "dashscope")
    monkeypatch.setattr(cfg, "base_url", "https://dashscope.aliyuncs.com/native-rerank")
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, json=json)
        return httpx.Response(
            200,
            json={"output": {"results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.1},
            ]}, "usage": {"total_tokens": 7}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(rerank_mod.httpx, "post", fake_post)
    assert rerank_mod.rerank("query", ["a", "b"]) == [0.1, 0.9]
    assert sent["url"] == "https://dashscope.aliyuncs.com/native-rerank"
    assert sent["json"] == {
        "model": "test-dashscope",
        "input": {"query": "query", "documents": ["a", "b"]},
        "parameters": {"return_documents": False},
    }


def test_rerank_siliconflow_request_unchanged(monkeypatch):
    rerank_mod, cfg = _rerank_on(monkeypatch, "siliconflow")
    monkeypatch.setattr(cfg, "base_url", "https://api.siliconflow.cn/v1")
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, json=json)
        return httpx.Response(
            200,
            json={"results": [{"index": 0, "relevance_score": 0.4}],
                  "meta": {"tokens": {"input_tokens": 5}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(rerank_mod.httpx, "post", fake_post)
    assert rerank_mod.rerank("query", ["a"]) == [0.4]
    assert sent["url"] == "https://api.siliconflow.cn/v1/rerank"
    assert sent["json"]["documents"] == ["a"]
    assert "input" not in sent["json"]


def test_retrieval_keys_read_separate_environment_names(monkeypatch):
    from citecheck.config import _retrieval_key

    data = {"llm": {
        "embedding": {"api_key_env": "TEST_EMBED_KEY"},
        "rerank": {"api_key_env": "TEST_RERANK_KEY"},
    }}
    monkeypatch.setenv("TEST_EMBED_KEY", "process-value")
    env = {"TEST_EMBED_KEY": "file-value", "TEST_RERANK_KEY": "rerank-value"}
    assert _retrieval_key(data, env, "embedding", "UNUSED") == "process-value"
    assert _retrieval_key(data, env, "rerank", "UNUSED") == "rerank-value"


def test_missing_retrieval_keys_warn_at_startup(monkeypatch, caplog):
    from citecheck.server import _warn_retrieval_keys

    s = get_settings()
    monkeypatch.setattr(s.llm.embedding, "enabled", True)
    monkeypatch.setattr(s.llm.rerank, "enabled", True)
    monkeypatch.setattr(s.llm.embedding, "api_key_env", "TEST_EMBED_KEY")
    monkeypatch.setattr(s.llm.rerank, "api_key_env", "TEST_RERANK_KEY")
    monkeypatch.setattr(s, "embedding_api_key", None)
    monkeypatch.setattr(s, "rerank_api_key", None)
    caplog.set_level("WARNING", logger="citecheck.server")
    _warn_retrieval_keys()
    assert "TEST_EMBED_KEY" in caplog.text and "using BM25 only" in caplog.text
    assert "TEST_RERANK_KEY" in caplog.text and "keeping the fused ranking" in caplog.text
