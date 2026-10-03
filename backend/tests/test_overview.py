"""Overview stage: venue exemplar scouting, shape profiles, critic."""

from __future__ import annotations

from pathlib import Path

import pytest

import citecheck.overview.run as run_mod
from citecheck.cache import Cache
from citecheck.llm.client import LLMResult
from citecheck.overview.profile import Shape, count_captions, manuscript_profile
from citecheck.overview.run import DIMS, Prepared, critique, prepare
from citecheck.overview.venues import Candidate, parse_volume, rank
from citecheck.parse.parser import parse_docx
from citecheck.schema import ExemplarPaper, Finding

FIXTURES = Path("tests/fixtures")

VOLUME_HTML = """
<span class=d-block><strong><a class=align-middle href=/2024.emnlp-main.0/>Proceedings</a></strong></span>
<span class=d-block><strong><a class=align-middle href=/2024.emnlp-main.1/><span class=acl-fixed-case>R</span>AG citation faithfulness</a></strong></span>
<div class="card bg-light mb-2 mb-lg-3 collapse abstract-collapse" id=abstract-2024--emnlp-main--1><div class="card-body p-3 small">We study whether retrieval augmented generation cites sources faithfully.</div></div>
<span class=d-block><strong><a class=align-middle href=/2024.emnlp-main.2/>Sentiment of tweets</a></strong></span>
<div class="card bg-light mb-2 mb-lg-3 collapse abstract-collapse" id=abstract-2024--emnlp-main--2><div class="card-body p-3 small">Twitter sentiment classification &amp; emoji.</div></div>
"""


def test_parse_volume_skips_frontmatter_and_joins_abstracts():
    papers = parse_volume(VOLUME_HTML, 2024)
    assert [p.id for p in papers] == ["2024.emnlp-main.1", "2024.emnlp-main.2"]
    assert papers[0].title == "RAG citation faithfulness"
    assert "cites sources faithfully" in papers[0].abstract
    assert papers[1].abstract.endswith("& emoji.")
    assert papers[0].pdf == "https://aclanthology.org/2024.emnlp-main.1.pdf"


def test_rank_prefers_topical_match_and_drops_zero_scores():
    pool = parse_volume(VOLUME_HTML, 2024) + [
        Candidate("2024.emnlp-main.3", "Speech translation", "audio", 2024)]
    top = rank(pool, "citation faithfulness in retrieval augmented generation", k=3)
    assert top[0].id == "2024.emnlp-main.1"
    assert all(c.id != "2024.emnlp-main.3" for c in top)


def test_count_captions_counts_distinct_numbers():
    lines = ["Table 1: Results.", "Table 1: (cont.)", "Figure 2. Overview",
             "Fig. 3: Ablation", "As Table 4 shows, ..."]
    assert count_captions(lines) == (1, 2)


def test_manuscript_profile_is_local_stats_plus_short_excerpt():
    parsed = parse_docx(FIXTURES / "numeric_en.docx")
    stats, excerpt = manuscript_profile(parsed)
    assert stats["n_references"] == len(parsed.references)
    assert stats["sections"] == len(parsed.sections)
    # only title / abstract / headings / captions — never the body
    body = max((p.text for p in parsed.paragraphs), key=len)
    assert body not in excerpt
    assert "Section headings:" in excerpt


def _patch_chat(monkeypatch, verdict: dict | None):
    async def fake(task, messages, schema, *, route="auto"):
        if task == "profile":
            return LLMResult(value=Shape(n_datasets=3, n_baselines=4,
                                         has_ablation=True), route="cloud")
        if verdict is None:
            return LLMResult(value=None, route="cloud", error="invalid output")
        return LLMResult(value=schema.model_validate(verdict), route="cloud")

    monkeypatch.setattr(run_mod, "chat_json", fake)
    import citecheck.overview.profile as prof_mod
    monkeypatch.setattr(prof_mod, "chat_json", fake)


def _prep() -> Prepared:
    ex = ExemplarPaper(id="2024.emnlp-main.1", title="RAG", year=2024,
                       url="https://aclanthology.org/2024.emnlp-main.1/",
                       stats={"n_datasets": 4})
    return Prepared("emnlp", {"n_tables": 2}, [ex])


@pytest.mark.asyncio
async def test_critique_clamps_and_fills_every_dimension(monkeypatch):
    _patch_chat(monkeypatch, {
        "overall": "near",
        "dims": [
            {"key": "experiments", "tier": "below", "note": "x" * 80},
            {"key": "bogus", "tier": "above", "note": "ignored"},
        ],
        "comment": "整体略低于该会议常见水平。" * 30,
    })
    findings = [Finding(id="f1", layer="support", severity="high", anchor=None,
                        title="t", detail="d")]
    ov = await critique(_prep(), findings)
    assert ov.status == "ok" and ov.overall == "near"
    assert [d.key for d in ov.dims] == list(DIMS)  # fixed order, no extras
    assert ov.dims[0].tier == "below" and len(ov.dims[0].note) <= 40
    assert all(d.tier == "na" for d in ov.dims[1:])
    assert len(ov.comment) <= 160


@pytest.mark.asyncio
async def test_critique_degrades_when_model_fails(monkeypatch):
    _patch_chat(monkeypatch, None)
    ov = await critique(_prep(), [])
    assert ov.status == "unavailable" and ov.note


@pytest.mark.asyncio
async def test_critique_without_exemplars_is_unavailable(monkeypatch):
    _patch_chat(monkeypatch, {"overall": "at"})
    ov = await critique(Prepared("emnlp", {}, [], note="没能获取"), [])
    assert ov.status == "unavailable" and ov.note == "没能获取"


@pytest.mark.asyncio
async def test_prepare_reads_exemplars_in_parallel(monkeypatch, tmp_path):
    _patch_chat(monkeypatch, None)
    cands = parse_volume(VOLUME_HTML, 2024)

    async def fake_pick(venue, query, years, client, cache, k=3):
        return cands[:1]

    async def fake_pdf(url, client, cache):
        return "Table 1: main results. Table 2: ablation. Limitations. ..."

    monkeypatch.setattr(run_mod, "pick_exemplars", fake_pick)
    monkeypatch.setattr(run_mod, "_fetch_pdf_text", fake_pdf)
    parsed = parse_docx(FIXTURES / "numeric_en.docx")
    prep = await prepare(parsed, "emnlp", None, Cache(tmp_path / "c.sqlite"))
    assert len(prep.exemplars) == 1
    ex = prep.exemplars[0].stats
    assert ex["n_datasets"] == 3 and ex["n_tables"] == 2 and ex["has_limitations"]
    assert prep.manuscript["n_baselines"] == 4  # manuscript read too


@pytest.mark.asyncio
async def test_prepare_unknown_venue():
    parsed = parse_docx(FIXTURES / "numeric_en.docx")
    prep = await prepare(parsed, "nope", None, None)  # type: ignore[arg-type]
    assert prep.exemplars == [] and prep.note
