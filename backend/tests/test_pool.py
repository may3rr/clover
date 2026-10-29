"""对标范文池：参考文献里的同刊论文、模型选择题、作者–年份格式的范文画像。"""

from __future__ import annotations

import pytest

import citecheck.llm.client as llm_client
from citecheck.distribution import pool as pool_mod
from citecheck.distribution.pool import match_cited, shortfall_note
from citecheck.distribution.registry import resolve_target
from citecheck.distribution.venue import _cites, _entries
from citecheck.llm.client import LLMResult
from citecheck.schema import RefCheck, Reference


def _ref(i: int, venue: str | None, raw: str = "", doi: str | None = None) -> Reference:
    return Reference(id=f"r{i}", label=str(i), raw=raw or f"[{i}] A. Title {i}. {venue or ''}",
                     title=f"Title {i}", venue=venue, doi=doi, year=2020 + i)


def _check(i: int, venue: str | None = None, doi: str | None = None) -> RefCheck:
    return RefCheck(ref_id=f"r{i}", status="verified",
                    matched={"venue": venue, "doi": doi, "title": f"Title {i}"})


@pytest.mark.asyncio
async def test_rules_read_every_venue_source():
    name, entry = resolve_target("数据分析与知识发现")
    refs = [
        _ref(1, "数据分析与知识发现"),  # structured venue
        _ref(2, None),  # verified record names it
        _ref(3, None, doi="10.11925/infotech.2096-3467.2025.0001"),  # DOI prefix
        _ref(4, "情报学报"),
        _ref(5, None, raw="[5] 王五. 题名[J]. 数据分析与知识发现, 2024, 8(1): 1-9."),  # entry
    ]
    checks = {"r2": _check(2, "Data Analysis and Knowledge Discovery")}
    got = await match_cited(refs, checks, {}, name, entry)
    assert [r.id for r in got] == ["r1", "r2", "r3", "r5"]


@pytest.mark.asyncio
async def test_model_can_only_pick_listed_names(monkeypatch):
    asked: list[str] = []

    async def fake(task, messages, schema, *, route="auto"):
        asked.append(messages[0]["content"])
        # 1 = "Chin. J. Comput.", 99 is not on the list
        return LLMResult(value=schema.model_validate({"ids": [1, 99, 0]}), route="cloud")

    monkeypatch.setattr(llm_client, "chat_json", fake)
    refs = [_ref(1, "Chin. J. Comput."), _ref(2, "软件学报"), _ref(3, "arXiv preprint")]
    got = await match_cited(refs, {}, {}, "计算机学报", None, use_model=True)
    assert [r.id for r in got] == ["r1"]
    # one question, listing only names the rules could not place, no arXiv
    assert len(asked) == 1
    assert "1. Chin. J. Comput." in asked[0] and "2. 软件学报" in asked[0]
    assert "arXiv" not in asked[0]


@pytest.mark.asyncio
async def test_model_off_or_failing_keeps_rules(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr(llm_client, "chat_json", boom)
    refs = [_ref(1, "计算机学报"), _ref(2, "Chin. J. Comput.")]
    assert [r.id for r in await match_cited(refs, {}, {}, "计算机学报", None,
                                            use_model=True)] == ["r1"]
    assert [r.id for r in await match_cited(refs, {}, {}, "计算机学报", None)] == ["r1"]


@pytest.mark.asyncio
async def test_cited_without_text_is_listed_not_counted(tmp_path):
    from citecheck.cache import Cache

    name, entry = resolve_target("EMNLP")
    refs = [_ref(1, "Proceedings of EMNLP 2019"), _ref(2, "EMNLP")]
    pool = await pool_mod.gather_pool(
        name, entry, refs=refs, checks=[], local={}, folder=[],
        cache=Cache(tmp_path / "c.sqlite"))
    assert [s.label for s in pool.sources] == ["2", "1"]  # newest first
    assert all(s.origin == "cited" and s.note == "没有取得原文，未参与统计"
               for s in pool.sources)


def test_shortfall_note():
    assert shortfall_note("计算机学报", 0, 0, 3) == (
        "参考文献和文献文件夹中没有找到《计算机学报》的论文，无法对标。"
        "可以在文献文件夹放入该刊近期发表的论文后重新体检。")
    note = shortfall_note("计算机学报", 2, 1, 3)
    assert "找到 2 篇《计算机学报》论文，其中 1 篇能完成统计，至少需要 3 篇" in note


def test_author_year_citations_and_entries():
    text = ("Pre-training helps (Dai and Le, 2015; Peters et al.,\n2018a, 2018b). "
            "Devlin et al. (2019) proposed BERT. See Table 2 (2019) and (Section 3).")
    cites = _cites(text, True)
    assert sum(n for _, n in cites) == 4 and len(cites) == 2
    refs = ("Andrew M Dai and Quoc V Le. 2015. Semi-supervised sequence learning. In NIPS. "
            "Jacob Devlin, Ming-Wei Chang. 2019. BERT: Pre-training. In Proceedings of NAACL. "
            "Matthew Peters. 2018a. Deep contextualized word representations. arXiv preprint.")
    entries = _entries(refs, True)
    assert len(entries) == 3
    assert "NAACL" in entries[1] and "arXiv" in entries[2]
    # numbered lists still split on [n]
    assert _entries("[1] 甲. 题名[J]. 学报, 2020. [2] 乙. 题名[M]. 2021.", False) == [
        "甲. 题名[J]. 学报, 2020.", "乙. 题名[M]. 2021."]


def test_pdf_url_prefers_record_then_anthology_then_arxiv():
    from citecheck.distribution.pool import _pdf_url

    ref = _ref(1, "EMNLP", doi="10.18653/v1/2023.emnlp-main.495")
    assert _pdf_url(ref, None) == "https://aclanthology.org/2023.emnlp-main.495.pdf"
    old = RefCheck(ref_id="r2", status="verified", matched={"doi": "10.18653/v1/d18-1259"})
    assert _pdf_url(_ref(2, "EMNLP"), old) == "https://aclanthology.org/D18-1259.pdf"
    oa = RefCheck(ref_id="r1", status="verified", matched={"pdf_url": "https://x.org/a.pdf"})
    assert _pdf_url(ref, oa) == "https://x.org/a.pdf"
    ax = RefCheck(ref_id="r3", status="verified", matched={"arxiv_id": "2303.08896"})
    assert _pdf_url(_ref(3, "EMNLP"), ax) == "https://arxiv.org/pdf/2303.08896"
    assert _pdf_url(_ref(4, "EMNLP"), None) is None
