"""中文期刊对标：exemplar profiles, built-in fallback, journal rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from citecheck.cache import Cache
from citecheck.distribution.registry import (
    builtin_baseline, find_venue, load_venues, mentions_venue, resolve_target)
from citecheck.distribution.venue import build_venue_benchmark, manuscript_stats, profile_pdf
from citecheck.library.scan import scan_folder
from citecheck.lint.venue_rules import check_venue_rules
from citecheck.parse import parse_docx
from libgen import cnki_article

FIXTURES = Path(__file__).parent / "fixtures"
VENUE = "数据分析与知识发现"


@pytest.fixture(scope="module")
def exemplars(tmp_path_factory):
    pytest.importorskip("reportlab")
    root = tmp_path_factory.mktemp("ex")
    for i in range(6):
        cnki_article(root / f"a{i}.pdf", f"范文题名第{i}篇研究", "张三，李四", VENUE,
                     "2026-05-01", n_refs=10 + i, recent=5)
    return scan_folder(root, Cache(root / "c.sqlite"))


def test_profile_pdf(exemplars):
    prof = profile_pdf(exemplars[0])
    assert prof is not None
    assert set(prof["sections"]) >= {"intro", "related", "method", "experiment", "conclusion"}
    assert prof["sections"]["related"]["cites"] == 5  # [4-6] [7] [8]
    assert prof["total_cites"] == 9
    vs = prof["venue_stats"]
    assert vs["n_refs"] == 10 and vs["recent_share"] == 0.5
    assert vs["foreign_share"] == 0 and vs["n_figures"] == 1 and vs["n_tables"] == 2


def test_build_venue_benchmark(exemplars):
    b = build_venue_benchmark(exemplars, VENUE)
    assert b["n_papers"] == 6 and b["language"] == "zh"
    assert b["venue_stats"]["n_refs"]["median"] == 12.5
    assert b["sections"]["related"]["share"]["median"] == pytest.approx(5 / 9)
    assert build_venue_benchmark(exemplars[:2], VENUE) is None  # too few


def test_registry_and_builtin_baseline():
    assert any(v["id"] == "dakd" for v in load_venues())
    v = find_venue("Data Analysis and Knowledge Discovery")
    assert v["id"] == "dakd" and find_venue("不存在的期刊") is None
    b = builtin_baseline(v)
    assert b["n_papers"] >= 20 and b["venue_stats"]["n_refs"]["median"] > 0
    # statistics only: no titles or text ship with the app
    assert "paper_ids" not in b and "title" not in str(b)


def test_resolve_target():
    assert resolve_target("  ") is None and resolve_target(None) is None
    assert resolve_target("《数据分析与知识发现》")[0] == VENUE
    name, entry = resolve_target("emnlp")
    assert name == "EMNLP" and entry["id"] == "emnlp"
    # an unknown venue still works, without registry entry
    assert resolve_target("计算机学报") == ("计算机学报", None)


@pytest.mark.parametrize("text, target, hit", [
    ("Proceedings of the 2018Conference on Empirical Methods in Natural Language "
     "Processing.Brussels", "EMNLP", True),
    ("In Proc. of EMNLP 2019", "EMNLP", True),
    ("Findings of the Association for Computational Linguistics: EMNLP 2020", "EMNLP", False),
    ("Proceedings of NAACL-HLT", "ACL", False),
    ("Proceedings of ACL-IJCNLP 2021", "ACL", True),
    ("Proceedings of the Workshop on Dialogue, ACL 2018", "ACL", False),
    ("Proceedings of the 56th Annual Meeting of the Association for Computational "
     "Linguistics.Melbourne", "ACL", True),
    ("张三. 标题[J]. 计算机学报, 2018, 41(3): 1-10.", "计算机学报", True),
    ("Pattern Recognition Letters", "Pattern Recognition", False),
    ("International Journal of Pattern Recognition and AI", "Pattern Recognition", False),
    ("Pattern Recognition, 2019, 88: 1-10", "Pattern Recognition", True),
    ("Data Analysis and Knowledge Discovery, 2025", VENUE, True),
])
def test_mentions_venue(text, target, hit):
    name, entry = resolve_target(target)
    assert mentions_venue(text, name, entry) is hit


def test_venue_rules():
    parsed = parse_docx(FIXTURES / "dakd_zh.docx")
    titles = {f.title for f in check_venue_rules(parsed, find_venue("dakd"), 2026)}
    assert "参考文献少于《数据分析与知识发现》要求的 6 条" in titles
    assert "缺少利益冲突声明" in titles
    assert "缺少作者贡献声明" not in titles  # the fixture has one
    assert "结构式摘要缺少要素" in titles  # only [目的]
    # r1/r3/r5 carry translations — no translation finding
    assert "中文文献缺少英文译文" not in titles
    stats = manuscript_stats(parsed, 2026)
    assert stats["n_refs"] == 5 and stats["foreign_share"] == 0.4


@pytest.mark.asyncio
async def test_pipeline_pools_cited_and_folder_papers(tmp_path, monkeypatch):
    """The manuscript cites two papers of the journal and the folder holds
    one more: three papers with text, enough to benchmark. The journal's
    rules apply."""
    import shutil

    from citecheck.pipeline import run_pipeline
    from test_pipeline import _client, _empty_transport, _patch_llm

    pytest.importorskip("reportlab")
    _patch_llm(monkeypatch)
    ref = tmp_path / "ref"
    ref.mkdir()
    # [3] and [5] of dakd_zh, as full articles, plus one uncited paper
    cnki_article(ref / "c3.pdf", "面向古典文学问答领域的大语言模型对抗幻觉优化方法研究",
                 "曾子明，徐康", VENUE, "2026-09-24", n_refs=10, recent=5)
    cnki_article(ref / "c5.pdf", "融合蕴含树和LLM的事实核查研究",
                 "韩明星，高宏宇，许莉薇，李佳轩", VENUE, "2026-04-01", n_refs=12, recent=6)
    cnki_article(ref / "u1.pdf", "范文题名第一篇研究", "张三，李四", VENUE,
                 "2026-05-01", n_refs=11, recent=5)
    shutil.copy(FIXTURES / "dakd_zh.docx", tmp_path / "p.docx")
    retrieval = _client(_empty_transport(), tmp_path)
    report = await run_pipeline(tmp_path / "p.docx", retrieval=retrieval,
                                cache=Cache(tmp_path / "c.sqlite"), library_dir=ref,
                                venue="Data Analysis and Knowledge Discovery")
    await retrieval.close()
    d = report.distribution
    assert d.venue == VENUE and d.venue_source == "exemplars" and d.n_papers == 3
    assert sorted((e.origin, e.label) for e in d.exemplars) == [
        ("cited", "3"), ("cited", "5"), ("folder", None)]
    assert d.comparable_density  # zh manuscript vs zh exemplars
    assert {s.key for s in d.venue_stats} >= {"n_refs", "recent_share"}
    assert any(f.title == "缺少利益冲突声明" for f in report.findings)
    assert report.overview is not None and report.overview.venue_name == VENUE


@pytest.mark.asyncio
async def test_pipeline_venue_without_papers(tmp_path, monkeypatch):
    """A venue the references never cite and no folder: no benchmark, and
    the report says what to do."""
    from citecheck.pipeline import run_pipeline
    from test_pipeline import _client, _empty_transport, _patch_llm

    _patch_llm(monkeypatch)
    retrieval = _client(_empty_transport(), tmp_path)
    report = await run_pipeline(FIXTURES / "dakd_zh.docx", retrieval=retrieval,
                                cache=Cache(tmp_path / "c.sqlite"), venue="计算机学报")
    await retrieval.close()
    assert report.distribution.venue is None
    ov = report.overview
    assert ov.status == "unavailable" and ov.venue_name == "计算机学报"
    assert ov.note.startswith("参考文献和文献文件夹中没有找到《计算机学报》的论文")
    assert "文献文件夹" in ov.note


@pytest.mark.asyncio
async def test_pipeline_without_venue_keeps_default(tmp_path, monkeypatch):
    from citecheck.pipeline import run_pipeline
    from test_pipeline import _client, _empty_transport, _patch_llm

    _patch_llm(monkeypatch)
    retrieval = _client(_empty_transport(), tmp_path)
    report = await run_pipeline(FIXTURES / "dakd_zh.docx", retrieval=retrieval,
                                cache=Cache(tmp_path / "c.sqlite"))
    await retrieval.close()
    d = report.distribution
    assert d.venue is None and d.venue_source is None and d.venue_stats == []
    assert d.benchmark_id == "arxiv_cs_cl"
    # blank: no benchmarking at all, not even from the cited DAKD papers
    assert report.overview is None
    assert not any("数据分析与知识发现" in f.title for f in report.findings)
