"""T4b distribution layer tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citecheck.distribution import layer as dist_mod
from citecheck.distribution.bench import load_benchmark, _DEFAULT
from citecheck.distribution.layer import count_words, run_distribution
from citecheck.llm.client import LLMResult
from citecheck.parse.parser import ParsedDocument, parse_docx
from citecheck.schema import (
    CitationMarker,
    Document,
    Paragraph,
    Reference,
    Section,
)

FIXTURES = Path("tests/fixtures")
BENCH_PATH = _DEFAULT


def bench_json(tmp_path, **over) -> str:
    """A synthetic benchmark file."""
    sections = {}
    for canon in ("intro", "related", "method", "experiment",
                  "discussion", "conclusion", "other"):
        sections[canon] = {
            "share": {"mean": 0.14, "median": 0.1, "q1": 0.05, "q3": 0.2},
            "density_per_1k_words": {"median": 5.0, "q1": 2.0, "q3": 8.0},
            "present_in": 40,
        }
    bench = {
        "id": "test", "name": "arXiv 计算语言学", "language": "en",
        "n_papers": 50, "built_at": "x", "paper_ids": [],
        "sections": sections,
        "sentence_refs": {
            "share_ge2": {"median": 0.3, "q1": 0.2, "q3": 0.4},
            "share_ge3": {"median": 0.1, "q1": 0.05, "q3": 0.2},
            "share_ge5": {"median": 0.0, "q1": 0.0, "q3": 0.05},
        },
    }
    bench.update(over)
    p = tmp_path / "bench.json"
    p.write_text(json.dumps(bench, ensure_ascii=False))
    return str(p)


def mk_parsed(sections: list[tuple[str, str, list[str]]],
              markers: list[tuple[int, str, list[int]]],
              n_refs: int = 6) -> ParsedDocument:
    """sections: [(title, canonical, [para texts])]; markers: (para_abs_idx,
    raw, ref numbers). Reference paragraphs appended at the end."""
    secs, paras = [], []
    texts: list[str] = []
    pi = 0
    for title, canon, pts in sections:
        sid = f"s{len(secs)}"
        head_pid = f"p{pi}"
        secs.append(Section(id=sid, title=title, canonical=canon,
                            heading_paragraph_id=head_pid))  # type: ignore[arg-type]
        for t in ([title] + pts):
            texts.append(t)
            paras.append(Paragraph(id=f"p{pi}", section_id=sid, text=t,
                                   char_offset=0))
            pi += 1
    refs = [
        Reference(id=f"r{i + 1}", raw=f"[{i + 1}] Ref {i + 1}.",
                  paragraph_id=f"p{pi + i}", label=str(i + 1))
        for i in range(n_refs)
    ]
    out_markers = []
    for k, (pidx, raw, nums) in enumerate(markers):
        start = texts[pidx].index(raw)
        out_markers.append(CitationMarker(
            id=f"m{k}", paragraph_id=f"p{pidx}", start=start,
            end=start + len(raw), raw=raw, kind="numeric",
            ref_ids=[f"r{n}" for n in nums]))
    return ParsedDocument(
        document=Document(citation_style="numeric"),
        sections=secs, paragraphs=paras, markers=out_markers,
        references=refs,
    )


def test_count_words():
    assert count_words("Hello world 你好世界 x-y.") == 2 + 4 + 1
    assert count_words("没有拉丁文字。") == 6


@pytest.mark.asyncio
async def test_metrics_on_fixture(tmp_path):
    p = parse_docx(FIXTURES / "numeric_en.docx")
    d, _ = await run_distribution(p, bench_path=bench_json(tmp_path),
                                  classify=False)
    by_canon = {s.canonical: s for s in d.sections}
    # method section: markers [1],[2],[2-5],[6],[1,4,16] -> 1+1+4+1+3 = 10
    assert by_canon["method"].citations == 10
    assert abs(sum(s.share for s in d.sections) - 1.0) < 1e-6
    total = sum(s.citations for s in d.sections)
    assert total == sum(len(m.ref_ids) for m in p.markers)
    # every share_flag is a real comparison
    assert all(s.share_flag in {"below", "within", "above"}
               for s in d.sections)


@pytest.mark.asyncio
async def test_share_flags_both_directions(tmp_path):
    dense = "Dense refs [1,2,3,4,5,6] everywhere."
    secs = [("Intro", "intro", ["One ref [1] and more text here."]),
            ("Related", "related", [dense] * 4)]
    markers = [(1, "[1]", [1])] + [
        (3 + i, "[1,2,3,4,5,6]", [1, 2, 3, 4, 5, 6]) for i in range(4)]
    p = mk_parsed(secs, markers)
    d, findings = await run_distribution(
        p, bench_path=bench_json(tmp_path), classify=False)
    by_canon = {s.canonical: s for s in d.sections}
    assert by_canon["intro"].share_flag == "below"    # 1/25 < q1 0.05
    assert by_canon["related"].share_flag == "above"  # 24/25 > q3 0.2
    # one merged finding per section even when share AND density are out
    f_rel = [f for f in findings if "相关工作" in f.title]
    assert len(f_rel) == 1 and f_rel[0].severity == "low"
    assert "占比" in f_rel[0].detail and "每千词" in f_rel[0].detail
    # anchored on the heading paragraph, spanning the whole heading text
    sec = [s for s in p.sections if s.canonical == "related"][0]
    assert f_rel[0].anchor.paragraph_id == sec.heading_paragraph_id


@pytest.mark.asyncio
async def test_density_flag_and_finding(tmp_path):
    # method with very few words but some citations -> above density q3=8
    secs = [("Method", "method", ["X [1,2] y." * 5])]
    p = mk_parsed(secs, [(1, "[1,2]", [1, 2])], n_refs=2)
    d, findings = await run_distribution(
        p, bench_path=bench_json(tmp_path), classify=False)
    sd = d.sections[0]
    assert sd.density_flag == "above"
    f = [x for x in findings if "分布" in x.title]
    assert len(f) == 1 and "每千词" in f[0].detail and "高于" in f[0].detail


@pytest.mark.asyncio
async def test_language_mismatch_density_na(tmp_path):
    secs = [("方法", "method", ["本段引用若干文献 [1,2] 展开说明。" * 4])]
    p = mk_parsed(secs, [(1, "[1,2]", [1, 2])], n_refs=2)
    d, findings = await run_distribution(
        p, bench_path=bench_json(tmp_path), classify=False)
    assert d.comparable_density is False and d.note
    assert all(s.density_flag == "na" for s in d.sections)
    assert not any("每千词" in f.detail for f in findings)


@pytest.mark.asyncio
async def test_stacking_finding(tmp_path):
    text = "Several lines of work [1,2,3,4,5] address this."
    secs = [("Intro", "intro", [text])]
    p = mk_parsed(secs, [(1, "[1,2,3,4,5]", [1, 2, 3, 4, 5])], n_refs=5)
    d, findings = await run_distribution(
        p, bench_path=bench_json(tmp_path), classify=False)
    f = [x for x in findings if "同时引用了 5 篇文献" in x.title]
    assert len(f) == 1 and f[0].severity == "medium"
    assert f[0].anchor.start == 0 and "[1,2,3,4,5]" in text[:f[0].anchor.end]
    assert d.sentence_refs.share_ge5 == 1.0


@pytest.mark.asyncio
async def test_stacking_negative(tmp_path):
    text = "Several lines of work [1,2,3,4] address this."
    p = mk_parsed([("Intro", "intro", [text])],
                  [(1, "[1,2,3,4]", [1, 2, 3, 4])], n_refs=4)
    d, findings = await run_distribution(
        p, bench_path=bench_json(tmp_path), classify=False)
    assert not any("同时引用" in f.title for f in findings)
    assert d.sentence_refs.share_ge5 == 0.0


@pytest.mark.asyncio
async def test_uncited_claim_positive(tmp_path):
    text = "Previous studies have shown that scaling helps. We verify it."
    p = mk_parsed([("Intro", "intro", [text])], [], n_refs=1)
    _, findings = await run_distribution(
        p, bench_path=bench_json(tmp_path), classify=False)
    f = [x for x in findings if "没有标注引用" in x.title]
    assert len(f) == 1 and f[0].severity == "medium"
    assert "Previous studies" in text[f[0].anchor.start:f[0].anchor.end]


@pytest.mark.asyncio
async def test_uncited_claim_negative_guards(tmp_path):
    # first-person sentence -> excluded even with a cue
    t1 = "Studies have shown that our method works. We report it here."
    # cue-less plain numbers never trigger
    t2 = "The dataset has 12345 rows and accuracy reached 92.5%."
    # cited sentence with a cue -> no finding
    t3 = "Prior work has addressed this problem [1]."
    # cue sentence in experiment section -> not flagged
    secs = [("Intro", "intro", [t1, t2]),
            ("Experiment", "experiment", [t3, "Studies have shown x."])]
    markers = [(4, "[1]", [1])]
    p = mk_parsed(secs, markers, n_refs=1)
    _, findings = await run_distribution(
        p, bench_path=bench_json(tmp_path), classify=False)
    flagged = [x for x in findings if "没有标注引用" in x.title]
    assert flagged == []


@pytest.mark.asyncio
async def test_function_classification_fake_llm(tmp_path, monkeypatch):
    async def fake(task, messages, schema, *, route="auto"):
        assert task == "function"
        return LLMResult(value=schema.model_validate({
            "items": [{"marker_id": "m0", "function": "method"},
                      {"marker_id": "m9", "function": "background"},
                      {"marker_id": "m0", "function": "bogus"}],
        }), route="cloud")

    monkeypatch.setattr(dist_mod, "chat_json", fake)
    p = mk_parsed([("Intro", "intro", ["We use X [1] here."])],
                  [(1, "[1]", [1])], n_refs=1)
    d, _ = await run_distribution(
        p, bench_path=bench_json(tmp_path), classify=True)
    assert d.functions == {"background": 0, "method": 1, "comparison": 0,
                           "result": 0, "critique": 0}
    assert d.marker_functions == {"m0": "method"}


@pytest.mark.skipif(not BENCH_PATH.exists(),
                    reason="benchmark not built yet")
def test_real_benchmark_shape():
    bench = load_benchmark()
    assert bench["id"] == "arxiv_cs_cl" and bench["n_papers"] >= 30
    means = sum(s["share"]["mean"] for s in bench["sections"].values())
    assert abs(means - 1.0) < 0.05
    assert set(bench["sentence_refs"]) == {"share_ge2", "share_ge3",
                                         "share_ge5"}
