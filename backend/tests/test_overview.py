"""Overview stage: shape profiles of the exemplar pool, critic."""

from __future__ import annotations

from pathlib import Path

import pytest

import citecheck.overview.run as run_mod
from citecheck.llm.client import LLMResult
from citecheck.overview.profile import Shape, count_captions, manuscript_profile
from citecheck.overview.run import DIMS, Prepared, critique, prepare
from citecheck.parse.parser import parse_docx
from citecheck.schema import ExemplarPaper, Finding

FIXTURES = Path("tests/fixtures")

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
    ex = ExemplarPaper(id="ref:1", title="RAG", year=2024, origin="cited", label="3",
                       stats={"n_datasets": 4})
    return Prepared("emnlp", "EMNLP", {"n_tables": 2}, [ex])


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
    ov = await critique(Prepared("emnlp", "EMNLP", {}, [], note="没能获取"), [])
    assert ov.status == "unavailable" and ov.note == "没能获取"


def _ctx(n: int):
    from citecheck.distribution.venue import ExemplarSource
    from citecheck.distribution.venue_metrics import Exemplar, VenueContext

    items = []
    for i in range(n):
        src = ExemplarSource(id=f"ref:{i}", title=f"Paper {i}", year=2018 + i,
                             origin="cited", label=str(i + 1),
                             raw_pages=["Table 1: main results. Table 2: ablation. Limitations."])
        items.append(Exemplar(src, {"title": src.title}, similar=i == 0))
    return VenueContext(venue="EMNLP", exemplars=items)


@pytest.mark.asyncio
async def test_prepare_reads_the_closest_exemplars(monkeypatch):
    _patch_chat(monkeypatch, None)
    parsed = parse_docx(FIXTURES / "numeric_en.docx")
    steps: list[str] = []
    prep = await prepare(parsed, "emnlp", "EMNLP", _ctx(6), on_step=steps.append)
    assert steps == [f"正在读取 {run_mod.READ_MAX} 篇范文"]
    # the topical match first, then the newest
    assert [e.id for e in prep.exemplars] == ["ref:0", "ref:5", "ref:4", "ref:3"]
    ex = prep.exemplars[0]
    assert ex.origin == "cited" and ex.label == "1"
    assert ex.stats["n_datasets"] == 3 and ex.stats["n_tables"] == 2
    assert ex.stats["has_limitations"]
    assert prep.manuscript["n_baselines"] == 4  # manuscript read too


@pytest.mark.asyncio
async def test_prepare_without_pool_carries_the_note():
    parsed = parse_docx(FIXTURES / "numeric_en.docx")
    prep = await prepare(parsed, "计算机学报", "计算机学报", None, "找到 1 篇")
    assert prep.exemplars == [] and prep.note == "找到 1 篇"
    ov = await critique(prep, [])
    assert ov.status == "unavailable" and ov.note == "找到 1 篇"
