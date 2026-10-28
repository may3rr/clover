"""F24 期刊对标细化：刊名识别、范文选择、细化指标与可追溯性。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from citecheck.cache import Cache
from citecheck.distribution.venue import profile_pdf, ref_type
from citecheck.library.scan import scan_folder
from citecheck.library.venue_match import (annotate_venues, match_target, paper_type,
                                           same_venue, venue_from_traces)
from citecheck.llm.client import LLMResult
from citecheck.parse import parse_docx
from libgen import _canvas, _lines, cnki_article, english

FIXTURES = Path(__file__).parent / "fixtures"
VENUE = "数据分析与知识发现"


def test_ref_type():
    assert ref_type("[1] 王静静. 题名[J]. 中国图书馆学报, 2023, 49(6): 41-50.") == "journal"
    assert ref_type("[2] 张三. 题名[D]. 北京: 北京大学, 2020.") == "thesis"
    assert ref_type("[3] 李四. 题名[C]//会议论文集. 2021.") == "conference"
    assert ref_type("[4] Qwen Team. Qwen3[EB/OL]. https://qwenlm.github.io.") == "web"
    assert ref_type("[5] Ji Z. Survey[J]. arXiv preprint arXiv:2202.03629, 2022.") == "preprint"
    assert ref_type("Lewis P. Retrieval-augmented generation. In: Proceedings of NeurIPS, 2020.") == "conference"


def test_same_venue_and_paper_type():
    assert same_venue("《数据分析与知识发现》", "Data Analysis and Knowledge Discovery")
    assert not same_venue("情报学报", VENUE)
    assert paper_type("基于大语言模型的命名实体识别研究现状") == "review"
    assert paper_type("A Survey on Hallucination") == "review"
    assert paper_type("融合蕴含树和LLM的事实核查研究") == "research"


@pytest.fixture()
def odd_folder(tmp_path):
    """No CNKI cover: an ISSN on page one, a journal in the running
    header, and a PDF whose journal only the model could tell."""
    pytest.importorskip("reportlab")
    ref = tmp_path / "ref"
    ref.mkdir()
    english(ref / "issn.pdf", "Knowledge graph completion with relation semantics",
            "Zhang San", None, body="Data Analysis ISSN 2096-3467 CN 10-1478/G2 " * 4)
    english(ref / "header.pdf", "Journal of Fake Studies Vol 3 Retrieval for review",
            "Li Si", None)
    english(ref / "plain.pdf", "Ranking passages with dense retrieval models",
            "Wang Wu", None, body="Published in Applied Retrieval Letters. " * 6)
    return ref


@pytest.mark.asyncio
async def test_venue_traces_header_and_model(odd_folder, monkeypatch):
    pdfs = {p.doc.filename: p for p in scan_folder(odd_folder, Cache(odd_folder / "c.sqlite"))}
    assert venue_from_traces(pdfs["issn.pdf"]) == (VENUE, "issn")
    assert match_target(pdfs["header.pdf"], "Journal of Fake Studies") == "header"
    assert match_target(pdfs["plain.pdf"], "Journal of Fake Studies") is None

    answers = {"Ranking": "Applied Retrieval Letters", "Journal": "Nature"}

    async def fake(task, messages, schema, *, route="auto"):
        text = messages[-1]["content"]
        name = next((v for k, v in answers.items() if k in text), None)
        return LLMResult(value=schema.model_validate({"venue": name}), route="cloud")

    import citecheck.llm.client as client_mod
    monkeypatch.setattr(client_mod, "chat_json", fake)
    await annotate_venues(list(pdfs.values()), set(), use_model=True)
    assert pdfs["issn.pdf"].doc.venue == VENUE and pdfs["issn.pdf"].doc.venue_via == "issn"
    assert pdfs["plain.pdf"].doc.venue == "Applied Retrieval Letters"
    assert pdfs["plain.pdf"].doc.venue_via == "model"
    # "Nature" is not printed on the page: an invented answer is dropped
    assert pdfs["header.pdf"].doc.venue is None


def _noisy_article(path: Path):
    """An exemplar whose body has numbered lines that are not headings."""
    c = _canvas(path)
    _lines(c, [f"《{VENUE}》网络首发论文", "题目： 噪声范文研究", "作者： 张三",
               "网络首发日期： 2026-03-01"])
    c.showPage()
    _lines(c, [
        "噪声范文研究", "1 引言", "大语言模型发展迅速[1]。", "2 相关研究", "已有方法[2,3]。",
        "3 IG-RAG框架设计", "本文框架如下。", "1. query (0.12)", "4.收敛判定", "若得分不变则停止。",
        "5个维度的高质量回答占比均低于基线", "4 实验与分析", "实验采用公开数据集[4]。",
        "表1 不同方法的结果对比", "5 e- 5", "6 结语", "本文方法有效。",
    ])
    c.showPage()
    _lines(c, ["参考文献："] + [f"[{i}] 作者{i}. 文献题名{i}[J]. 情报学报, 2025, 1(2): 3-4."
                             for i in range(1, 5)], size=9)
    c.save()


def test_heading_filter_and_captions(tmp_path):
    pytest.importorskip("reportlab")
    _noisy_article(tmp_path / "n.pdf")
    pdf = scan_folder(tmp_path, Cache(tmp_path / "c.sqlite"))[0]
    prof = profile_pdf(pdf)
    titles = [h["title"] for h in prof["headings"]]
    assert titles == ["引言", "相关研究", "IG-RAG框架设计", "实验与分析", "结语"]
    assert all(h["page"] == 2 for h in prof["headings"])
    assert [c["text"] for c in prof["captions"]] == ["表1不同方法的结果对比"]
    assert prof["ref_types"] == ["journal"] * 4 and prof["ref_page"] == 3


def _fake_llm(monkeypatch, seen: list | None = None):
    """structure: type "IG-RAG框架设计"-like titles as method; profile:
    one verifiable and one invented quote; function: m1 = method."""

    async def fake(task, messages, schema, *, route="auto"):
        text = messages[-1]["content"]
        if seen is not None:
            seen.append(task)
        if task == "structure":
            items = [{"i": int(ln.split(".")[0]), "canonical": "method"}
                     for ln in text.splitlines() if ln[:1].isdigit() and "." in ln[:3]]
            payload = {"items": items, "venue": None}
        elif task == "profile":
            payload = {"n_datasets": {"value": 2, "evidence": "范文题名"},
                       "has_ablation": {"value": True, "evidence": "这句话不在论文里"},
                       "has_case_study": {"value": False, "evidence": None},
                       "has_human_eval": {"value": None, "evidence": None}}
        else:
            payload = {"items": [{"marker_id": "m1", "function": "method"},
                                 {"marker_id": "m2", "function": "background"}]}
        return LLMResult(value=schema.model_validate(payload), route="cloud")

    import citecheck.distribution.layer as dist_mod
    import citecheck.llm.client as client_mod
    monkeypatch.setattr(client_mod, "chat_json", fake)
    monkeypatch.setattr(dist_mod, "chat_json", fake)


@pytest.fixture(scope="module")
def exemplar_dir(tmp_path_factory):
    pytest.importorskip("reportlab")
    root = tmp_path_factory.mktemp("venue")
    for i in range(6):
        cnki_article(root / f"a{i}.pdf", f"范文题名第{i}篇研究", "张三，李四", VENUE,
                     "2026-05-01", n_refs=10 + i, recent=5)
    _noisy_article(root / "noisy.pdf")
    return root


@pytest.mark.asyncio
async def test_compare_traceable(exemplar_dir, monkeypatch):
    from citecheck.distribution.layer import run_distribution
    from citecheck.distribution.venue_metrics import prepare_venue

    _fake_llm(monkeypatch)
    parsed = parse_docx(FIXTURES / "dakd_zh.docx")
    pdfs = scan_folder(exemplar_dir, Cache(exemplar_dir / "c.sqlite"))
    bench, ctx = await prepare_venue(pdfs, VENUE, parsed, use_model=True)
    assert bench["n_papers"] == 7 and ctx.overrides.get("IG-RAG框架设计") == "method"
    noisy = next(e for e in ctx.used if e.pdf.doc.filename == "noisy.pdf")
    assert "method" in noisy.prof["sections"]  # the model typed the heading

    dist, findings = await run_distribution(parsed, bench=bench, venue=VENUE,
                                            venue_source="exemplars", venue_ctx=ctx)
    m = {x.key: x for x in dist.venue_metrics}
    assert {"share:related", "n_refs", "type:journal", "func:method",
            "elem:n_datasets", "present:method", "n_tables"} <= set(m)
    # every exemplar value names its page; references point at the list
    nr = m["n_refs"]
    assert len(nr.exemplars) == 7 and all(v.page for v in nr.exemplars)
    assert nr.value == 5 and nr.anchors  # the manuscript's reference heading
    assert m["share:related"].exemplars[0].quote == "相关研究"
    # a quote that is not in the exemplar drops the value to unknown
    assert m["elem:n_datasets"].exemplars[0].value == 2
    assert m["elem:n_datasets"].exemplars[0].quote == "范文题名"
    assert "elem:has_ablation" not in m or all(
        v.value is None for v in m["elem:has_ablation"].exemplars)
    assert m["func:method"].exemplars[0].value == 0.5
    # findings carry the keys of the measures behind them
    venue_f = [f for f in findings if f.metrics]
    assert venue_f and all(set(f.metrics) <= set(m) for f in venue_f)
    assert all("推荐" not in f.detail and f.severity == "low" for f in venue_f)
    assert {e.doc_id for e in dist.exemplars} == {p.doc.id for p in pdfs}
    assert sum(e.similar for e in dist.exemplars) <= 3


@pytest.mark.asyncio
async def test_compare_without_model_keeps_local_measures(exemplar_dir, monkeypatch):
    from citecheck.distribution.layer import run_distribution
    from citecheck.distribution.venue_metrics import prepare_venue

    seen: list[str] = []
    _fake_llm(monkeypatch, seen)
    parsed = parse_docx(FIXTURES / "dakd_zh.docx")
    pdfs = scan_folder(exemplar_dir, Cache(exemplar_dir / "c.sqlite"))
    bench, ctx = await prepare_venue(pdfs, VENUE, parsed, use_model=False)
    assert not seen  # nothing about the exemplars left the machine
    dist, _ = await run_distribution(parsed, bench=bench, venue=VENUE,
                                     venue_source="exemplars", classify=False, venue_ctx=ctx)
    keys = {x.key for x in dist.venue_metrics}
    assert "n_refs" in keys and not any(k.startswith(("func:", "elem:")) for k in keys)


@pytest.mark.asyncio
async def test_pipeline_uses_selected_exemplars(tmp_path, monkeypatch):
    from citecheck.pipeline import run_pipeline
    from test_pipeline import _client, _empty_transport, _patch_llm

    pytest.importorskip("reportlab")
    _patch_llm(monkeypatch)
    ref = tmp_path / "ref"
    ref.mkdir()
    for i in range(6):
        cnki_article(ref / f"a{i}.pdf", f"范文题名第{i}篇研究", "张三，李四", VENUE,
                     "2026-05-01", n_refs=10 + i, recent=5)
    shutil.copy(FIXTURES / "dakd_zh.docx", tmp_path / "p.docx")
    ids = sorted(p.doc.id for p in scan_folder(ref, Cache(tmp_path / "c.sqlite")))

    async def run(picked):
        retrieval = _client(_empty_transport(), tmp_path)
        try:
            return await run_pipeline(tmp_path / "p.docx", retrieval=retrieval,
                                      cache=Cache(tmp_path / "c.sqlite"), library_dir=ref,
                                      library_exemplars=picked)
        finally:
            await retrieval.close()

    report = await run(ids[:5])
    d = report.distribution
    assert d.venue == VENUE and d.venue_source == "exemplars" and d.n_papers == 5
    assert sorted(e.doc_id for e in d.exemplars) == ids[:5]
    assert report.library.exemplar_ids == ids[:5] and d.venue_metrics
    # four picked: too few, the built-in baseline takes over
    d = (await run(ids[:4])).distribution
    assert d.venue_source == "builtin" and not d.venue_metrics


def test_library_venue_endpoint(exemplar_dir):
    from fastapi.testclient import TestClient

    from citecheck.server import TOKEN, app

    c = TestClient(app)
    h = {"Authorization": f"Bearer {TOKEN}"}
    r = c.post("/library/venue", headers=h, data={"library": str(exemplar_dir),
                                                  "venue": "Data Analysis and Knowledge Discovery"})
    body = r.json()
    assert r.status_code == 200 and body["library"]["venue"] == "Data Analysis and Knowledge Discovery"
    assert len(body["library"]["venue_match_ids"]) == 7
    assert body["baseline"]["source"] == "exemplars" and body["entry"]["id"] == "dakd"
    one = body["library"]["exemplar_ids"][0]
    r = c.post("/library/venue", headers=h, data={"library": str(exemplar_dir), "venue": "情报学报",
                                                  "linked": json.dumps([one])})
    body = r.json()
    assert body["library"]["venue_match_ids"] == [] and body["baseline"]["source"] is None
