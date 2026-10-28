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
