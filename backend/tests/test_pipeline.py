"""T6 tests: pipeline orchestration + FastAPI server."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from citecheck.cache import Cache
from citecheck.llm.client import LLMResult
from citecheck.parse.parser import parse_docx
from citecheck.pipeline import run_pipeline
from citecheck.refs.sources import RetrievalClient
from citecheck.schema import Report

FIXTURES = Path("tests/fixtures")


def _patch_llm(monkeypatch, responses: dict | None = None):
    """Route every task through a fake client."""
    responses = responses or {}

    async def fake(task, messages, schema, *, route="auto"):
        payload = responses.get(task, {"items": [], "claims": []})
        return LLMResult(value=schema.model_validate(payload), route="cloud")

    import citecheck.distribution.layer as dist_mod
    import citecheck.lint.typos as typo_mod
    import citecheck.llm.client as client_mod
    import citecheck.support.claims as claims_mod
    import citecheck.support.judge as judge_mod
    for mod in (dist_mod, typo_mod, client_mod, claims_mod, judge_mod):
        if hasattr(mod, "chat_json"):
            monkeypatch.setattr(mod, "chat_json", fake)


def _empty_transport() -> httpx.MockTransport:
    """Every source answers with an empty result set (real no-hits)."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "crossref" in host:
            if request.url.path.startswith("/works/"):
                return httpx.Response(404)
            return httpx.Response(200, json={"message": {"items": []}})
        if "openalex" in host:
            return httpx.Response(200, json={"results": []})
        if "semanticscholar" in host:
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _dead_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    return httpx.MockTransport(handler)


def _client(transport, tmp_path) -> RetrievalClient:
    c = RetrievalClient(cache=Cache(tmp_path / "cache.sqlite"))
    c._client = httpx.AsyncClient(
        transport=transport, follow_redirects=True, timeout=5.0)
    return c


@pytest.mark.asyncio
async def test_pipeline_full(tmp_path, monkeypatch):
    _patch_llm(monkeypatch)
    retrieval = _client(_empty_transport(), tmp_path)
    events: list[dict] = []
    report = await run_pipeline(
        FIXTURES / "numeric_unordered_en.docx", emit=events.append,
        retrieval=retrieval, cache=Cache(tmp_path / "c.sqlite"))
    await retrieval.close()

    assert isinstance(report, Report)
    assert {e["type"] for e in events} >= {"parsed", "layer", "done"}
    assert events[-1]["type"] == "done"
    # parsed event carries the skeleton outline and precedes layer events
    parsed_ev = next(e for e in events if e["type"] == "parsed")
    assert events.index(parsed_ev) < next(
        i for i, e in enumerate(events) if e["type"] == "layer")
    outline = parsed_ev["outline"]
    assert outline["references"] == len(report.references)
    para_ids = {p["id"] for s in outline["sections"]
                for p in s["paragraphs"]}
    assert para_ids == {p.id for p in report.paragraphs}
    assert all(0 <= m <= 1 for s in outline["sections"]
               for p in s["paragraphs"] for m in p["markers"])
    # layer-done events carry relative anchors for the skeleton
    done_layers = [e for e in events
                   if e["type"] == "layer" and e["status"] == "done"]
    anchored = [a for e in done_layers for a in e.get("anchors", [])]
    n_anchored = sum(1 for f in report.findings if f.anchor is not None)
    assert len(anchored) == n_anchored
    for a in anchored:
        assert a["paragraph_id"] in para_ids
        assert 0 <= a["start_rel"] <= a["end_rel"] <= 1
        assert a["severity"] in {"high", "medium", "low"}
    # every layer ran and finished
    for layer in ("authenticity", "support", "distribution", "norms"):
        assert report.meta.layers[layer].status == "done"
    # all sources responded empty -> english refs are not_found
    assert all(c.status in {"not_found", "unverifiable"}
               for c in report.ref_checks)
    # support ran with no sources -> all undetermined
    assert all(s.label == "undetermined" for s in report.support_checks)
    # findings sorted by document position, ids stable
    pos = {p.id: i for i, p in enumerate(report.paragraphs)}
    keys = [(1, pos.get(f.anchor.paragraph_id, 0), f.anchor.start)
            if f.anchor else (0, 0, 0) for f in report.findings]
    assert keys == sorted(keys)
    assert [f.id for f in report.findings] == [
        f"f{i}" for i in range(1, len(report.findings) + 1)]
    assert [r.id for r in report.revisions] == [
        f"v{i}" for i in range(1, len(report.revisions) + 1)]
    assert report.distribution is not None and report.distribution.n_papers == 150
    assert report.meta.duration_s >= 0


@pytest.mark.asyncio
async def test_pipeline_retrieval_dead(tmp_path, monkeypatch):
    _patch_llm(monkeypatch)
    retrieval = _client(_dead_transport(), tmp_path)
    events: list[dict] = []
    report = await run_pipeline(
        FIXTURES / "numeric_unordered_en.docx", emit=events.append,
        retrieval=retrieval, cache=Cache(tmp_path / "c.sqlite"))
    await retrieval.close()

    assert isinstance(report, Report)
    # either authenticity completed as all-unverifiable, or the layer
    # failed while the others still produced output
    auth = report.meta.layers["authenticity"]
    if auth.status == "done":
        assert all(c.status == "unverifiable" for c in report.ref_checks)
    else:
        assert auth.status == "failed" and auth.error
    assert report.meta.layers["norms"].status == "done"
    assert report.meta.layers["distribution"].status == "done"
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_pipeline_bad_file(tmp_path):
    bad = tmp_path / "not_a_doc.docx"
    bad.write_text("hello")
    events: list[dict] = []
    with pytest.raises(Exception):
        await run_pipeline(bad, emit=events.append)
    assert events[-1]["type"] == "failed"
    assert "无法读取这个文件" in events[-1]["error"]


# ------------------------------------------------------------- server


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    _patch_llm(monkeypatch)
    retrieval = _client(_dead_transport(), tmp_path)

    import citecheck.pipeline as pipe
    import citecheck.server as srv

    monkeypatch.setattr(pipe, "RetrievalClient", lambda *a, **kw: retrieval)
    transport = httpx.ASGITransport(app=srv.app)
    return srv, httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0)


async def _wait_done(client: httpx.AsyncClient, job_id: str) -> list[str]:
    lines: list[str] = []
    async with client.stream("GET", f"/jobs/{job_id}/events") as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            lines.append(line)
            if line.startswith("data:"):
                ev = json.loads(line[5:].strip())
                if ev["type"] in {"done", "failed"}:
                    return lines
    return lines


@pytest.mark.asyncio
async def test_server_flow(app_client, tmp_path):
    srv, client = app_client
    r = await client.get("/health")
    assert r.status_code == 200
    r = await client.get("/benchmarks")
    assert any(b["id"] == "arxiv_cs_cl" for b in r.json())

    # report 409 while running / before export
    src = tmp_path / "paper.docx"
    src.write_bytes((FIXTURES / "numeric_unordered_en.docx").read_bytes())
    r = await client.post("/analyze", data={"path": str(src)})
    job = r.json()["job_id"]
    lines = await _wait_done(client, job)
    assert any('"done"' in ln for ln in lines)
    # events replay: layer events precede done
    data_lines = [ln for ln in lines if ln.startswith("data:")]
    types = [json.loads(ln[5:])["type"] for ln in data_lines]
    assert types[-1] == "done" and "layer" in types
    assert "parsed" in types and types.index("parsed") == 0

    r = await client.get(f"/jobs/{job}/report")
    assert r.status_code == 200
    rep = r.json()
    assert rep["document"]["filename"] == "paper.docx"
    Report.model_validate(rep)  # validates against the shared schema

    r = await client.post(f"/jobs/{job}/export")
    assert r.status_code == 200, r.text
    out = Path(r.json()["path"])
    assert out.exists() and "引用体检" in out.name
    # tmp sources are treated as uploads -> land in ~/Downloads
    assert out != src and src.read_bytes() == (
        FIXTURES / "numeric_unordered_en.docx").read_bytes()
    out.unlink()  # keep ~/Downloads clean
    await client.aclose()


@pytest.mark.asyncio
async def test_server_upload(app_client, tmp_path):
    srv, client = app_client
    data = (FIXTURES / "numeric_unordered_en.docx").read_bytes()
    r = await client.post(
        "/analyze", files={"file": ("up.docx", data, "application/octet-stream")})
    assert r.status_code == 200 and r.json()["job_id"] in srv.JOBS
    await client.aclose()


@pytest.mark.asyncio
async def test_server_token(app_client, monkeypatch):
    srv, client = app_client
    monkeypatch.setattr(srv, "TOKEN", "sekret")
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/benchmarks")).status_code == 401
    assert (await client.get(
        "/benchmarks", headers={"X-Citecheck-Token": "sekret"}
    )).status_code == 200
    assert (await client.get("/benchmarks?token=sekret")).status_code == 200
    await client.aclose()
