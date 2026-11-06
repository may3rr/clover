"""Privacy mode and the send list (llm/privacy.py, llm/sendlog.py).

No real cloud call: the OpenAI client, the embedding and rerank HTTP
posts and the local engine are all faked.
"""

import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from citecheck.cache import Cache
from citecheck.config import Settings, get_settings
from citecheck.llm import client as llm
from citecheck.llm import local, privacy, sendlog


class Out(BaseModel):
    ok: bool = True


@pytest.fixture
def usage_db(monkeypatch, tmp_path):
    cache = Cache(tmp_path / "usage.sqlite")
    monkeypatch.setattr(llm, "_cache", cache)
    monkeypatch.setattr(llm, "_cloud_client", None)
    monkeypatch.setattr(llm, "_cloud_sem", None)
    monkeypatch.setattr(local, "_engine", None)
    return cache


def _settings(privacy_on: bool, local_on: bool) -> Settings:
    return Settings(llm={"local": {"enabled": local_on}},
                    privacy={"enabled": privacy_on})


def _fake_cloud(monkeypatch, calls: list):
    """A fake OpenAI client: _cloud_call (and its usage logging) runs for real."""

    class Completions:
        async def create(self, **kw):
            calls.append(kw["messages"])
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2),
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_get_cloud", lambda: (fake, llm.PrioritySemaphore(4)))


# ------------------------------------------------------------- routing


@pytest.mark.asyncio
@pytest.mark.parametrize("task", privacy.PRIVATE_TASKS)
async def test_private_task_skipped_without_local_model(monkeypatch, usage_db, task):
    calls: list = []
    _fake_cloud(monkeypatch, calls)
    monkeypatch.setattr(llm, "get_settings", lambda: _settings(True, False))
    with llm.stats_scope() as stats:
        r = await llm.chat_json(task, [{"role": "user", "content": "稿件正文 json"}], Out)
    assert r.value is None and r.skipped
    assert calls == []  # never sent to the cloud
    assert stats.skipped == {task: 1} and stats.cloud == 0


@pytest.mark.asyncio
async def test_private_task_forced_local_even_when_not_listed(monkeypatch, usage_db):
    """typo is not in [llm.local].tasks: privacy mode still keeps it local,
    and a failing local model does not fall back to the cloud."""
    calls: list = []
    _fake_cloud(monkeypatch, calls)
    monkeypatch.setattr(llm, "get_settings", lambda: _settings(True, True))
    served = []

    async def good_local(messages, max_tokens=1024):
        served.append(messages)
        return '{"ok": true}'

    monkeypatch.setattr(local, "generate_or_raise", good_local)
    r = await llm.chat_json("typo", [{"role": "user", "content": "段落 json"}], Out)
    assert r.route == "local" and r.value == Out()
    assert len(served) == 1 and calls == []

    async def bad_local(messages, max_tokens=1024):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(local, "generate_or_raise", bad_local)
    r = await llm.chat_json("typo", [{"role": "user", "content": "另一段 json"}], Out)
    assert r.value is None and calls == []


@pytest.mark.asyncio
async def test_explicit_cloud_route_cannot_bypass_privacy(monkeypatch, usage_db):
    calls: list = []
    _fake_cloud(monkeypatch, calls)
    monkeypatch.setattr(llm, "get_settings", lambda: _settings(True, False))
    r = await llm.chat_json("typo", [{"role": "user", "content": "x json"}], Out,
                            route="cloud")
    assert r.skipped and calls == []


@pytest.mark.asyncio
async def test_judge_goes_to_cloud_in_privacy_mode(monkeypatch, usage_db):
    calls: list = []
    _fake_cloud(monkeypatch, calls)
    monkeypatch.setattr(llm, "get_settings", lambda: _settings(True, False))
    r = await llm.chat_json("judge", [{"role": "user", "content": "论断 json"}], Out)
    assert r.route == "cloud" and len(calls) == 1


@pytest.mark.asyncio
async def test_local_only_scope_keeps_judge_local(monkeypatch, usage_db):
    calls: list = []
    _fake_cloud(monkeypatch, calls)
    monkeypatch.setattr(llm, "get_settings", lambda: _settings(True, False))
    with privacy.local_only():
        r = await llm.chat_json("judge", [{"role": "user", "content": "本文提出 json"}], Out)
    assert r.skipped and calls == []


@pytest.mark.asyncio
async def test_privacy_off_keeps_default_routes(monkeypatch, usage_db):
    calls: list = []
    _fake_cloud(monkeypatch, calls)
    monkeypatch.setattr(llm, "get_settings", lambda: _settings(False, False))
    r = await llm.chat_json("typo", [{"role": "user", "content": "x json"}], Out)
    assert r.route == "cloud" and len(calls) == 1


def test_skipped_tasks_listing():
    assert privacy.skipped_tasks(_settings(True, True)) == []
    off = privacy.skipped_tasks(_settings(True, False))
    assert set(privacy.PRIVATE_TASKS) <= set(off) and "own_claim" in off


# ------------------------------------------------- own-contribution rule


@pytest.mark.parametrize("text", [
    "本文提出一种基于图神经网络的检索方法[3]。",
    "我们进一步构建了一个中文数据集 [12]。",
    "与 BERT [5] 相比，本文的方法在三个数据集上更好。",
    "本研究设计了两阶段框架，参考了文献[7]。",
    "We propose a retrieval model inspired by [4].",
    "In this paper, we introduce a benchmark (Smith et al., 2020).",
    "This work presents a new approach to QA [2].",
    "Our method outperforms RAG [9] on TriviaQA.",
    "Compared with [3], our proposed framework is faster.",
])
def test_own_contribution_detected(text):
    assert privacy.own_contribution(text)


@pytest.mark.parametrize("text", [
    "Lewis 等人提出了检索增强生成方法[3]。",
    "本文采用文献[3]的评价指标。",
    "已有研究表明大模型会产生幻觉[1, 2]。",
    "Vaswani et al. propose the Transformer [1].",
    "We follow the setting of [4].",
    "They propose a model that we use as a baseline [6].",
    "Prior work [2] shows our understanding of RAG is limited.",
    "",
    None,
])
def test_ordinary_claims_not_flagged(text):
    assert not privacy.own_contribution(text)


@pytest.mark.asyncio
async def test_own_claim_pair_skipped_without_local(monkeypatch, usage_db):
    """Privacy mode, own-contribution sentence, no local model: the pair
    ends undetermined without any model call or source fetch."""
    from citecheck.schema import Claim, Reference
    from citecheck.support import layer as layer_mod

    s = get_settings()
    monkeypatch.setattr(s.privacy, "enabled", True)
    monkeypatch.setattr(s.llm.local, "enabled", False)

    async def boom(*a, **kw):
        raise AssertionError("must not be called")

    monkeypatch.setattr(layer_mod, "build_source", boom)
    monkeypatch.setattr(layer_mod, "judge_claim", boom)
    ref = Reference(id="r1", raw="[1] A. Author. Title. 2020.", title="Title")
    parsed = SimpleNamespace(references=[ref], paragraphs=[], markers=[])
    run = layer_mod.SupportRun(parsed, cache=usage_db)
    await run._claims_task
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=10,
                  text="本文提出一种新方法", marker_ids=["m0"],
                  sentence="本文提出一种新方法[1]。")
    with llm.stats_scope() as stats:
        await run._do(claim, "r1")
    out = run._out[("c0", "r1")]
    assert out.label == "undetermined" and out.rationale == layer_mod.OWN_SKIPPED
    assert stats.skipped == {"own_claim": 1}
    findings = layer_mod._support_findings(parsed, [(claim, "r1")], [out])
    assert findings == []  # not reported as a missing source
    await run._http.aclose()


# ---------------------------------------------------- embeddings / rerank


def test_embedding_api_off_in_privacy_mode(monkeypatch):
    from citecheck.llm import embed as embed_mod

    s = get_settings()
    monkeypatch.setenv("CITECHECK_EMBED", "1")
    monkeypatch.setattr(s.llm.embedding, "enabled", True)
    monkeypatch.setattr(s, "embedding_api_key", "k")
    assert embed_mod.enabled()
    monkeypatch.setattr(s.privacy, "enabled", True)
    assert not embed_mod.enabled()
    # the on-device backend stays allowed
    monkeypatch.setattr(s.llm.embedding, "backend", "openvino")
    monkeypatch.setattr(s.llm.embedding, "local_model", "/models/emb")
    assert embed_mod.enabled()


def test_rerank_api_allowed_except_local_only(monkeypatch):
    from citecheck.llm import rerank as rr

    s = get_settings()
    monkeypatch.setenv("CITECHECK_RERANK", "1")
    monkeypatch.setattr(s.llm.rerank, "enabled", True)
    monkeypatch.setattr(s, "rerank_api_key", "k")
    monkeypatch.setattr(s.privacy, "enabled", True)
    assert rr.enabled()
    with privacy.local_only():
        assert not rr.enabled()


def test_embed_and_rerank_rows_record_chars_and_categories(monkeypatch, tmp_path):
    from citecheck.llm import embed as embed_mod
    from citecheck.llm import rerank as rr

    s = get_settings()
    monkeypatch.setenv("CITECHECK_EMBED", "1")
    monkeypatch.setenv("CITECHECK_RERANK", "1")
    monkeypatch.setattr(s.llm.embedding, "enabled", True)
    monkeypatch.setattr(s, "embedding_api_key", "k")
    monkeypatch.setattr(s.llm.rerank, "enabled", True)
    monkeypatch.setattr(s, "rerank_api_key", "k")
    cache = Cache(tmp_path / "u.sqlite")
    monkeypatch.setattr(embed_mod, "_cache", cache)
    monkeypatch.setattr(embed_mod, "_down_until", 0.0)
    monkeypatch.setattr(rr, "_cache", cache)
    monkeypatch.setattr(rr, "_down_until", 0.0)

    def fake_post(url, headers, json, timeout):
        req = httpx.Request("POST", url)
        if url.endswith("/embeddings"):
            data = [{"index": i, "embedding": [1.0, float(i)]}
                    for i in range(len(json["input"]))]
            return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 5}},
                                  request=req)
        return httpx.Response(200, json={"results": [
            {"index": i, "relevance_score": 0.5} for i in range(len(json["documents"]))]},
            request=req)

    monkeypatch.setattr(embed_mod.httpx, "post", fake_post)
    monkeypatch.setattr(rr.httpx, "post", fake_post)
    with llm.doc_scope("paper.docx", "run1"):
        embed_mod.embed(["window one", "window two!"])
        embed_mod.embed(["the claim"], query=True)
        rr.rerank("the claim", ["window one", "window two!"])
    rows = cache.usage_for_run("run1")
    assert [r["task"] for r in rows] == ["embed", "embed", "rerank"]
    assert all(r["route"] == "cloud" for r in rows)
    assert rows[0]["chars"] == len("window one") + len("window two!")
    assert rows[0]["category"] == "excerpt"
    q = json.loads(rows[1]["parts"])
    assert q[0]["c"] == "claim" and q[0]["t"] == "the claim"  # instruction stripped
    assert rows[2]["chars"] == len("the claim") + 21
    cats = [p["c"] for p in json.loads(rows[2]["parts"])]
    assert cats == ["claim", "excerpt", "excerpt"]


# ------------------------------------------------------------ send list


@pytest.mark.asyncio
async def test_chat_rows_record_chars_parts_and_run(monkeypatch, usage_db):
    calls: list = []
    _fake_cloud(monkeypatch, calls)
    monkeypatch.setattr(llm, "get_settings", lambda: _settings(False, False))
    msg = [{"role": "user", "content": "判断 json：论断 A；片段 B"}]
    with llm.doc_scope("paper.docx", "run7"):
        await llm.chat_json("judge", msg, Out, parts=[
            ("claim", "论断 A。", "论断 A。"), ("reference", "[1] Ref."),
            ("excerpt", "片段 B")])
        # cache hit: recorded as cached, nothing sent
        await llm.chat_json("judge", msg, Out, parts=[("claim", "论断 A。")])
    rows = usage_db.usage_for_run("run7")
    assert len(rows) == 2
    sent, hit = rows
    assert sent["route"] == "cloud" and not sent["cached"]
    assert sent["chars"] == len(msg[0]["content"])
    assert sent["category"] == "reference"  # the part with the most characters
    assert [p["c"] for p in json.loads(sent["parts"])] == ["claim", "reference", "excerpt"]
    assert hit["cached"] == 1


def test_old_database_gains_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE llm_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "provider TEXT NOT NULL, model TEXT NOT NULL, task TEXT NOT NULL, "
        "prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL, "
        "cached INTEGER NOT NULL DEFAULT 0)")
    con.execute("INSERT INTO llm_usage (ts, provider, model, task, prompt_tokens, "
                "completion_tokens) VALUES ('2026-01-01T00:00:00', 'dashscope', 'm', 'judge', 1, 1)")
    con.commit()
    con.close()
    c = Cache(path)
    cols = {r[1] for r in c._conn.execute("PRAGMA table_info(llm_usage)")}
    assert {"doc", "run", "route", "chars", "category", "parts"} <= cols
    c.record_usage("dashscope", "m", "judge", 1, 1, run="r", route="cloud",
                   chars=5, category="claim", parts="[]")
    assert len(c.usage_for_run("r")) == 1
    assert sum(r["calls"] for r in c.usage_summary()) == 2  # the old row survives
    c.close()


def test_summary_numbers_match_recorded_rows(tmp_path):
    c = Cache(tmp_path / "s.sqlite")

    def row(task, route, parts, cached=False, chars=None):
        packed = sendlog.pack(parts)
        c.record_usage("p", "m", task, 1, 1, cached, run="R", route=route,
                       chars=chars if chars is not None else sum(p["n"] for p in packed) + 100,
                       parts=json.dumps(packed, ensure_ascii=False))

    claim = "本句引用了文献[1]。"
    row("judge", "cloud", [("claim", claim), ("reference", "[1] Ref one."),
                           ("excerpt", "excerpt text one")])
    row("judge", "cloud", [("claim", claim), ("reference", "[1] Ref one."),
                           ("excerpt", "excerpt text two")])
    row("structure", "cloud", [("reference", "[1] Ref one."), ("reference", "[2] Ref two.")])
    row("typo", "local", [("manuscript", "本机处理的段落")])  # not sent
    row("judge", "cloud", [("claim", claim)], cached=True)  # not sent
    rows = c.usage_for_run("R")
    s = sendlog.summarize(rows, 5000, privacy=True, skipped={"typo": 3})
    sent = [r for r in rows if r["route"] == "cloud" and not r["cached"]]
    assert s.requests == 3 == len(sent)
    assert s.sent_chars == sum(r["chars"] for r in sent)
    assert s.content_chars == sum(p["n"] for r in sent for p in json.loads(r["parts"]))
    assert s.cached_requests == 1 and s.local_requests == 1
    by = {x.category: x for x in s.categories}
    assert by["claim"].count == 1 and by["claim"].items[0].times == 2
    assert by["reference"].count == 2
    assert by["excerpt"].count == 2
    assert "manuscript" not in by
    assert s.manuscript_chars == 5000
    assert s.manuscript_sent_chars == len(claim)
    assert s.skipped[0].task == "typo" and s.skipped[0].count == 3
    assert s.skipped[0].label == "错别字检查"
    c.close()


def test_summary_caps_items():
    rows = [{"route": "cloud", "cached": 0, "task": "judge", "chars": 10,
             "parts": json.dumps(sendlog.pack([("excerpt", f"片段 {i}")]))}
            for i in range(sendlog.ITEM_CAP + 7)]
    s = sendlog.summarize(rows, 100)
    cat = s.categories[0]
    assert cat.count == sendlog.ITEM_CAP + 7
    assert len(cat.items) == sendlog.ITEM_CAP and cat.truncated == 7


def test_pack_truncates_display_text():
    p = sendlog.pack([("claim", "x" * 1000), ("claim", "  ")])
    assert len(p) == 1 and p[0]["n"] == 1000 and len(p[0]["t"]) == 160


# ------------------------------------------------------ settings switch


def test_put_config_privacy_switch(tmp_path, monkeypatch):
    import tomllib

    from fastapi.testclient import TestClient

    import citecheck.config as cfgmod
    from citecheck.server import TOKEN, app

    H = {"Authorization": f"Bearer {TOKEN}"}

    cfg = tmp_path / "config.toml"
    cfg.write_text(cfgmod._CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8"),
                   encoding="utf-8")
    monkeypatch.setattr(cfgmod, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(cfgmod, "_ENV_PATH", tmp_path / ".env")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        body = client.get("/config", headers=H).json()
        assert body["privacy_mode"] is False
        assert body["local_model"] is False
        assert "错别字检查" in body["privacy_skipped"]
        body = client.put("/config", headers=H, json={"privacy_mode": True}).json()
        assert body["privacy_mode"] is True
        assert tomllib.loads(cfg.read_text(encoding="utf-8"))["privacy"]["enabled"] is True
        get_settings.cache_clear()
        assert get_settings().privacy.enabled is True  # survives a reload
        body = client.put("/config", headers=H, json={"privacy_mode": False}).json()
        assert body["privacy_mode"] is False
    finally:
        get_settings.cache_clear()


# ------------------------------------------------------------- pipeline


async def _run_fixture(monkeypatch, tmp_path, privacy_on: bool):
    """The whole pipeline on a fixture with a fake OpenAI client: every
    chat_json call (routing, caching, usage logging) runs for real."""
    from test_pipeline import FIXTURES, _client, _empty_transport

    from citecheck.pipeline import run_pipeline

    calls: list = []

    class Completions:
        async def create(self, **kw):
            calls.append(kw["messages"])
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_get_cloud", lambda: (fake, llm.PrioritySemaphore(8)))
    usage = Cache(tmp_path / "usage.sqlite")
    monkeypatch.setattr(llm, "_cache", usage)
    monkeypatch.setattr(local, "_engine", None)
    s = get_settings()
    monkeypatch.setattr(s.privacy, "enabled", privacy_on)
    monkeypatch.setattr(s.llm.local, "enabled", False)
    retrieval = _client(_empty_transport(), tmp_path)
    report = await run_pipeline(
        FIXTURES / "numeric_unordered_en.docx", retrieval=retrieval,
        cache=Cache(tmp_path / "c.sqlite"))
    await retrieval.close()
    return report, usage, calls


@pytest.mark.asyncio
async def test_report_send_list_matches_recorded_rows(monkeypatch, tmp_path):
    report, usage, calls = await _run_fixture(monkeypatch, tmp_path, False)
    send = report.meta.send
    assert send is not None and send.run and not send.privacy
    rows = usage.usage_for_run(send.run)
    cloud = [r for r in rows if r["route"] == "cloud" and not r["cached"]]
    assert send.requests == len(cloud) == len(calls) > 0
    assert send.sent_chars == sum(r["chars"] for r in cloud)
    # chars are what the fake client actually received
    assert send.sent_chars == sum(sum(len(m["content"]) for m in c) for c in calls)
    assert send.manuscript_chars > 0
    # privacy off: the typo check sends paragraphs (unchanged behaviour)
    assert any(x.category == "manuscript" for x in send.categories)


@pytest.mark.asyncio
async def test_privacy_pipeline_sends_no_manuscript_text(monkeypatch, tmp_path):
    report, usage, calls = await _run_fixture(monkeypatch, tmp_path, True)
    send = report.meta.send
    assert send.privacy
    rows = usage.usage_for_run(send.run)
    cloud_tasks = {r["task"] for r in rows if r["route"] == "cloud"}
    assert not cloud_tasks & set(privacy.PRIVATE_TASKS)
    assert all(x.category not in ("manuscript", "exemplar") for x in send.categories)
    skipped = {x.task for x in send.skipped}
    assert {"typo", "structure", "extract", "function"} <= skipped
    assert send.requests == len(calls)
    # no all-zero function shares compared against the benchmark
    assert report.distribution.functions is None
