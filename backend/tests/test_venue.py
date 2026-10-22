"""中文期刊对标：exemplar profiles, built-in fallback, journal rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from citecheck.cache import Cache
from citecheck.distribution.registry import (
    builtin_baseline, detect_from_manuscript, find_venue, load_venues)
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
    assert build_venue_benchmark(exemplars[:4], VENUE) is None  # too few


def test_registry_and_builtin_baseline():
    assert any(v["id"] == "dakd" for v in load_venues())
    v = find_venue("Data Analysis and Knowledge Discovery")
    assert v["id"] == "dakd" and find_venue("不存在的期刊") is None
    b = builtin_baseline(v)
    assert b["n_papers"] >= 20 and b["venue_stats"]["n_refs"]["median"] > 0
    # statistics only: no titles or text ship with the app
    assert "paper_ids" not in b and "title" not in str(b)


def test_detect_only_from_front_matter():
    # dakd_zh cites DAKD papers in its reference list: cited, not targeted
    assert detect_from_manuscript(parse_docx(FIXTURES / "dakd_zh.docx")) is None


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
async def test_pipeline_falls_back_to_builtin(tmp_path, monkeypatch):
    """Folder with only 3 exemplars, user names the journal: the
    built-in baseline is used and the journal's rules apply."""
    import shutil

    from citecheck.pipeline import run_pipeline
    from libgen import build_library
    from test_pipeline import _client, _empty_transport, _patch_llm

    _patch_llm(monkeypatch)
    ref = build_library(tmp_path)
    shutil.copy(FIXTURES / "dakd_zh.docx", tmp_path / "p.docx")
    retrieval = _client(_empty_transport(), tmp_path)
    report = await run_pipeline(tmp_path / "p.docx", retrieval=retrieval,
                                cache=Cache(tmp_path / "c.sqlite"), library_dir=ref,
                                library_venue=VENUE)
    await retrieval.close()
    d = report.distribution
    assert d.venue == VENUE and d.venue_source == "builtin"
    assert d.comparable_density  # zh manuscript vs zh baseline
    assert {s.key for s in d.venue_stats} >= {"n_refs", "recent_share"}
    assert any(f.title == "缺少利益冲突声明" for f in report.findings)


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
