"""T3 tests: evidence verbatim check, claim extraction, judge accuracy.

The 10 claim–source pairs live in tests/fixtures/llm/support_pairs.json.
Default run replays recorded Qwen responses; CITECHECK_LIVE=1 calls the
real model (and record_llm.py refreshes the recording).
"""

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

from citecheck.llm import client as llm
from citecheck.llm import local
from citecheck.schema import CitationMarker, Claim, Paragraph
from citecheck.support import claims as claims_mod
from citecheck.support import judge as judge_mod
from citecheck.support.claims import extract_claims, split_sentences
from citecheck.support.evidence import locate_evidence, normalize_text
from citecheck.support.judge import JudgeOut
from citecheck.support.layer import evaluate_with_excerpt
from citecheck.cache import Cache

PAIRS_PATH = Path(__file__).parent / "fixtures" / "llm" / "support_pairs.json"
PAIRS = json.loads(PAIRS_PATH.read_text())
LIVE = os.environ.get("CITECHECK_LIVE") == "1"


# ------------------------------------------------------------ evidence


def test_normalize_quotes_and_ws():
    assert normalize_text('he  said  “yes”') == 'he said "yes"'
    assert normalize_text("a\u00a0b") == "a b"


def test_locate_evidence_offset_in_original_coords():
    excerpt = 'First sentence.   Second “quoted” sentence here.'
    span = locate_evidence('Second "quoted" sentence', excerpt)
    assert span is not None
    assert excerpt[span[0] : span[1]].startswith("Second")


def test_locate_evidence_nfkc_fullwidth():
    excerpt = "模型［见图］完成检测"
    span = locate_evidence("[见图]", excerpt)
    assert span is not None
    assert excerpt[span[0] : span[1]] == "［见图］"


def test_locate_evidence_failure():
    assert locate_evidence("not present at all", "some other text") is None
    assert locate_evidence("", "x") is None
    assert locate_evidence("x", None) is None


# ------------------------------------------------------------ sentences


def test_sentence_split_no_false_cuts():
    text = (
        "Vaswani et al. (2017) proposed the Transformer. It uses attention, "
        "e.g. scaled dot-product attention, with 3.5 multiplier. Fig. 2 shows "
        "the architecture. 研究表明该方法有效。"
    )
    sents = split_sentences(text)
    assert len(sents) == 4
    assert "et al." in sents[0].text
    assert "3.5" in sents[1].text
    assert sents[2].text.startswith("Fig. 2")


def test_sentence_offsets():
    text = "First.  Second sentence."
    sents = split_sentences(text)
    for s in sents:
        assert text[s.start : s.end] == s.text


# ------------------------------------------------------------ claims


@pytest.mark.asyncio
async def test_extract_claims_with_fake_llm(monkeypatch):
    para = Paragraph(
        id="p0", section_id="s0",
        text="Transformers work well on many tasks [1] in practice.",
        char_offset=0,
    )
    marker = CitationMarker(
        id="m0", paragraph_id="p0", start=40, end=43, raw="[1]", ref_ids=["r1"]
    )

    async def fake(task, messages, schema, **kw):
        return llm.LLMResult(
            value=schema(claims=[{"text": "Transformers work well on many tasks",
                                  "marker_ids": ["m0"]}]),
            route="local",
        )

    monkeypatch.setattr(claims_mod, "chat_json", fake)
    claims = await extract_claims(para, [marker])
    assert len(claims) == 1
    c = claims[0]
    assert para.text[c.start : c.end] == "Transformers work well on many tasks"
    assert c.marker_ids == ["m0"]
    assert c.sentence == para.text


@pytest.mark.asyncio
async def test_extract_filters_foreign_marker_ids(monkeypatch):
    """The local model may emit marker ids that are not in the sentence;
    keep only ids that are, and give uncovered markers a fallback claim."""
    text = ("Attention helps sequence models [1] "
            "while scaling also matters [2] here.")
    m0 = CitationMarker(id="m0", paragraph_id="p0", start=32, end=35,
                        raw="[1]", ref_ids=["r1"])
    m1 = CitationMarker(id="m1", paragraph_id="p0", start=63, end=66,
                        raw="[2]", ref_ids=["r2"])
    para = Paragraph(id="p0", section_id="s0", text=text, char_offset=0)
    assert text[32:35] == "[1]" and text[63:66] == "[2]"

    async def fake(task, messages, schema, **kw):
        return llm.LLMResult(
            value=schema(claims=[{
                "text": "Attention helps sequence models",
                "marker_ids": ["m0", "m99"],  # m99 does not exist
            }]),
            route="local",
        )

    monkeypatch.setattr(claims_mod, "chat_json", fake)
    claims = await extract_claims(para, [m0, m1])
    # foreign id dropped; uncovered m1 got its own fallback claim
    assert claims[0].marker_ids == ["m0"]
    assert any(set(c.marker_ids) == {"m1"} for c in claims)
    covered = {mid for c in claims for mid in c.marker_ids}
    assert covered == {"m0", "m1"}
    for c in claims:
        assert set(c.marker_ids) <= {"m0", "m1"}


@pytest.mark.asyncio
async def test_extract_short_claim_falls_back(monkeypatch):
    """Junk fragment claims ('reported in', 'Following earlier work') are
    rejected; the whole sentence minus markers is used instead."""
    text = "Baseline GloVe vectors underperform [1] on this task."
    marker = CitationMarker(id="m0", paragraph_id="p0", start=36, end=39,
                            raw="[1]", ref_ids=["r1"])
    para = Paragraph(id="p0", section_id="s0", text=text, char_offset=0)
    assert text[36:39] == "[1]"

    async def fake(task, messages, schema, **kw):
        return llm.LLMResult(
            value=schema(claims=[{"text": "Baseline GloVe",
                                  "marker_ids": ["m0"]}]),
            route="local",
        )

    monkeypatch.setattr(claims_mod, "chat_json", fake)
    claims = await extract_claims(para, [marker])
    assert len(claims) == 1
    assert "underperform" in claims[0].text
    assert "[1]" not in claims[0].text


@pytest.mark.asyncio
async def test_extract_claims_non_substring_falls_back(monkeypatch):
    para = Paragraph(
        id="p0", section_id="s0",
        text="Transformers work well [1].", char_offset=0,
    )
    marker = CitationMarker(
        id="m0", paragraph_id="p0", start=23, end=26, raw="[1]", ref_ids=["r1"]
    )

    async def fake(task, messages, schema, **kw):
        return llm.LLMResult(
            value=schema(claims=[{"text": "text that is NOT in the sentence",
                                  "marker_ids": ["m0"]}]),
            route="cloud",
        )

    monkeypatch.setattr(claims_mod, "chat_json", fake)
    claims = await extract_claims(para, [marker])
    assert len(claims) == 1
    assert claims[0].start == 0
    # trailing marker text excluded from the claim span
    assert para.text[claims[0].start : claims[0].end] == "Transformers work well"


@pytest.mark.asyncio
async def test_extract_claims_llm_failure_falls_back(monkeypatch):
    para = Paragraph(
        id="p0", section_id="s0", text="Attention helps [2].", char_offset=0
    )
    marker = CitationMarker(
        id="m0", paragraph_id="p0", start=16, end=19, raw="[2]", ref_ids=["r2"]
    )

    async def dead(task, messages, schema, **kw):
        return llm.LLMResult(value=None, route="cloud")

    monkeypatch.setattr(claims_mod, "chat_json", dead)
    claims = await extract_claims(para, [marker])
    assert len(claims) == 1 and claims[0].marker_ids == ["m0"]


# ------------------------------------------------------------ judge


@pytest.mark.asyncio
async def test_evidence_not_in_source_downgrades(monkeypatch):
    async def fake(task, messages, schema, **kw):
        return llm.LLMResult(
            value=JudgeOut(label="supported",
                           evidence="hallucinated evidence not in source",
                           rationale="x"),
            route="cloud",
        )

    monkeypatch.setattr(judge_mod, "chat_json", fake)
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=5, text="claim",
                  marker_ids=["m0"])
    check = await evaluate_with_excerpt(claim, "r1", "real source text", "T", "abstract")
    assert check.label == "undetermined"
    assert check.rationale == "证据未能在原文中定位"


@pytest.mark.asyncio
async def test_empty_evidence_downgrades(monkeypatch):
    async def fake(task, messages, schema, **kw):
        return llm.LLMResult(
            value=JudgeOut(label="supported", evidence=None, rationale="x"),
            route="cloud",
        )

    monkeypatch.setattr(judge_mod, "chat_json", fake)
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=5, text="claim",
                  marker_ids=["m0"])
    check = await evaluate_with_excerpt(claim, "r1", "excerpt", "T", "abstract")
    assert check.label == "undetermined"
    assert check.rationale == "模型未给出原文证据"


@pytest.mark.asyncio
async def test_router_fallback_counters(monkeypatch):
    """extract tries local first; local raises -> cloud serves; the call
    counts under the serving route."""
    async def bad_local(messages, max_tokens=1024):
        raise RuntimeError("unavailable")

    async def good_cloud(model, messages, task):
        return '{"claims": []}'

    monkeypatch.setattr(local, "generate_or_raise", bad_local)
    monkeypatch.setattr(llm, "_cloud_call", good_cloud)
    monkeypatch.setattr(llm, "_cache", Cache(str(
        Path(__file__).parent / ".tmp_llm.sqlite")))
    from citecheck.config import Settings
    monkeypatch.setattr(llm, "get_settings",
                        lambda: Settings(llm={"local": {"enabled": True}}))
    from citecheck.support.claims import _ClaimsOut
    with llm.stats_scope() as stats:
        r = await llm.chat_json("extract", [{"role": "user", "content": "x"}],
                                _ClaimsOut)
    assert r.route == "cloud" and r.value is not None
    assert stats.local == 0 and stats.cloud == 1


@pytest.mark.asyncio
async def test_evidence_reask_recovers(monkeypatch):
    """Unlocatable evidence triggers exactly one correction re-ask."""
    calls = []

    async def fake(task, messages, schema, **kw):
        calls.append(task)
        ev = "not in source" if len(calls) == 1 else "real source text"
        return llm.LLMResult(
            value=JudgeOut(label="supported", evidence=ev, rationale="x"),
            route="cloud",
        )

    monkeypatch.setattr(judge_mod, "chat_json", fake)
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=5, text="claim",
                  marker_ids=["m0"])
    check = await evaluate_with_excerpt(
        claim, "r1", "real source text", "T", "abstract")
    assert calls == ["judge", "judge"]
    assert check.label == "supported"
    assert check.evidence_span == (0, 16)


@pytest.mark.asyncio
async def test_review_cascade_overrides(monkeypatch):
    """partial/unsupported escalate to review; the review verdict wins."""
    calls = []

    async def fake(task, messages, schema, **kw):
        calls.append(task)
        label = "unsupported" if task == "judge" else "supported"
        return llm.LLMResult(
            value=JudgeOut(label=label, evidence="real source text",
                           rationale="x"),
            route="cloud",
        )

    monkeypatch.setattr(judge_mod, "chat_json", fake)
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=5, text="claim",
                  marker_ids=["m0"])
    check = await evaluate_with_excerpt(
        claim, "r1", "real source text", "T", "abstract")
    assert calls == ["judge", "review"]
    assert check.label == "supported"


@pytest.mark.asyncio
async def test_review_not_called_on_supported(monkeypatch):
    calls = []

    async def fake(task, messages, schema, **kw):
        calls.append(task)
        return llm.LLMResult(
            value=JudgeOut(label="supported", evidence="real source text",
                           rationale="x"),
            route="cloud",
        )

    monkeypatch.setattr(judge_mod, "chat_json", fake)
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=5, text="claim",
                  marker_ids=["m0"])
    check = await evaluate_with_excerpt(
        claim, "r1", "real source text", "T", "abstract")
    assert calls == ["judge"]
    assert check.label == "supported"


@pytest.mark.asyncio
async def test_review_fallback_on_error(monkeypatch):
    async def fake(task, messages, schema, **kw):
        if task == "judge":
            return llm.LLMResult(
                value=JudgeOut(label="unsupported",
                               evidence="real source text", rationale="x"),
                route="cloud")
        if task == "review":
            return llm.LLMResult(value=None, route="cloud",
                                 error="status=403 code=AllocationQuota.FreeTierOnly")
        return llm.LLMResult(
            value=JudgeOut(label="undetermined", evidence=None,
                           rationale="不足以判断"),
            route="cloud")

    monkeypatch.setattr(judge_mod, "chat_json", fake)
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=5, text="claim",
                  marker_ids=["m0"])
    check = await evaluate_with_excerpt(
        claim, "r1", "real source text", "T", "abstract")
    assert check.label == "undetermined"


@pytest.mark.asyncio
async def test_review_total_failure_keeps_first_pass(monkeypatch):
    async def fake(task, messages, schema, **kw):
        if task == "judge":
            return llm.LLMResult(
                value=JudgeOut(label="unsupported",
                               evidence="real source text", rationale="x"),
                route="cloud")
        return llm.LLMResult(value=None, route="cloud", error="boom")

    monkeypatch.setattr(judge_mod, "chat_json", fake)
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=5, text="claim",
                  marker_ids=["m0"])
    check = await evaluate_with_excerpt(
        claim, "r1", "real source text", "T", "abstract")
    assert check.label == "unsupported"
    assert check.evidence == "real source text"


# ------------------------------------------------------------ layer


@pytest.mark.asyncio
async def test_supportcheck_refs_bounded_by_claim_markers(monkeypatch, tmp_path):
    """Invariant: every SupportCheck.ref_id is in the union of ref_ids of
    its claim's markers — even when the extractor invents marker ids."""
    from citecheck.parse.parser import ParsedDocument
    from citecheck.schema import Document, Reference, RefCheck, Section
    from citecheck.support.layer import run_support

    text = ("Attention helps sequence models [1] "
            "while scaling also matters [2] here.")
    para = Paragraph(id="p0", section_id="s0", text=text, char_offset=0)
    markers = [
        CitationMarker(id="m0", paragraph_id="p0", start=32, end=35,
                       raw="[1]", ref_ids=["r1"]),
        CitationMarker(id="m1", paragraph_id="p0", start=63, end=66,
                       raw="[2]", ref_ids=["r2"]),
    ]
    refs = [
        Reference(id="r1", raw="ref one", title="Ref One", paragraph_id="p9"),
        Reference(id="r2", raw="ref two", title="Ref Two", paragraph_id="p10"),
    ]
    parsed = ParsedDocument(
        document=Document(), sections=[Section(id="s0", title="t", canonical="other")],
        paragraphs=[para], markers=markers, references=refs,
    )
    ref_checks = [
        RefCheck(ref_id="r1", status="verified",
                 matched={"title": "Ref One",
                          "abstract": "We study attention in sequence models "
                                      "and show consistent gains across tasks "
                                      "in a controlled evaluation with ablations "
                                      "and careful baselines for comparison."}),
        RefCheck(ref_id="r2", status="verified",
                 matched={"title": "Ref Two",
                          "abstract": "Scaling neural networks improves "
                                      "downstream performance; we quantify "
                                      "the effect across model sizes and data "
                                      "regimes with controlled experiments."}),
    ]

    async def fake_extract(task, messages, schema, **kw):
        return llm.LLMResult(
            value=schema(claims=[{
                "text": "Attention helps sequence models",
                "marker_ids": ["m0", "m99"],
            }]),
            route="local",
        )

    async def fake_judge(task, messages, schema, **kw):
        return llm.LLMResult(
            value=JudgeOut(label="undetermined", rationale="不足以判断"),
            route="cloud")

    monkeypatch.setattr(claims_mod, "chat_json", fake_extract)
    monkeypatch.setattr(judge_mod, "chat_json", fake_judge)

    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(404)))
    try:
        claims, checks, findings = await run_support(
            parsed, ref_checks, cache=Cache(tmp_path / "s.sqlite"), http=http
        )
    finally:
        await http.aclose()

    marker_refs = {m.id: set(m.ref_ids) for m in markers}
    claim_by_id = {c.id: c for c in claims}
    for sc in checks:
        cl = claim_by_id[sc.claim_id]
        allowed = set().union(*(marker_refs[mid] for mid in cl.marker_ids))
        assert sc.ref_id in allowed


# ------------------------------------------------------------ sources


def test_drop_reference_tail():
    from citecheck.support.sources import _drop_reference_tail

    body = "Main text " * 60 + " References Smith, J. 2020. Some work."
    out = _drop_reference_tail(body)
    assert "Smith, J." not in out and out.startswith("Main text")
    # heading in the first half is not a tail cut
    early = "References cited below. " + "Body " * 100
    assert _drop_reference_tail(early) == early


def test_ref_entry_window_filter():
    from citecheck.support.sources import _looks_like_ref_entry

    assert _looks_like_ref_entry(
        "Bengio, Y. et al., 2013. On the difficulty of training recurrent "
        "neural networks. arXiv preprint arXiv:1211.5063"
    )
    assert not _looks_like_ref_entry(
        "We train the model for 100 epochs and report test accuracy."
    )


def test_abstract_quality_gate():
    from citecheck.refs.sources import abstract_ok

    junk = ("Jacob Devlin, Ming-Wei Chang, Kenton Lee, Kristina Toutanova. "
            "Proceedings of the 2019 Conference of the North American Chapter")
    assert not abstract_ok(junk)
    assert not abstract_ok("short.")
    assert not abstract_ok(None)
    good = ("We introduce a new language representation model which stands "
            "for bidirectional encoder representations from transformers and "
            "obtain state-of-the-art results on eleven tasks.")
    assert abstract_ok(good)


@pytest.mark.asyncio
async def test_abstract_fallback_to_arxiv(tmp_path, monkeypatch):
    """Junk matched.abstract is rejected; the chain falls through to the
    arXiv API via arxiv_id."""
    import citecheck.support.sources as src_mod

    real_abs = ("We propose a method that improves translation quality "
                "substantially across benchmarks and ablation settings.") * 2

    def handler(request):
        if "/api/query" in str(request.url):
            return httpx.Response(
                200,
                text=f"<feed><entry><summary>{real_abs}</summary></entry></feed>")
        return httpx.Response(404)  # no pdf

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(src_mod, "_arxiv_throttle", lambda: asyncio.sleep(0))
    matched = {
        "title": "Some paper",
        "abstract": "A. Author, B. Writer, C. Person. Proceedings of X 2020.",
        "arxiv_id": "1701.00001",
    }
    src = await src_mod.build_source(
        matched, "claim about translation", cache=Cache(tmp_path / "s.sqlite"),
        client=http)
    await http.aclose()
    assert src.kind == "abstract"
    assert "translation" in src.excerpt


# ------------------------------------------------------------ pairs


@pytest.mark.asyncio
@pytest.mark.parametrize("pair", PAIRS["pairs"], ids=[p["id"] for p in PAIRS["pairs"]])
async def test_judge_pair_accuracy(pair, monkeypatch):
    claim = Claim(id="c0", paragraph_id="p0", start=0,
                  end=len(pair["claim"]), text=pair["claim"], marker_ids=["m0"])
    if LIVE:
        # real Qwen call; also refresh the recording
        check = await evaluate_with_excerpt(
            claim, "r1", pair["excerpt"], pair["title"], "abstract")
        PAIRS["recorded"][pair["id"]] = check.model_dump()
    else:
        rec = PAIRS["recorded"].get(pair["id"])
        assert rec is not None, f"{pair['id']} not recorded; run record_llm.py"
        out = JudgeOut(label=rec["label"], evidence=rec.get("evidence"),
                       rationale=rec.get("rationale", ""))

        async def fake(task, messages, schema, **kw):
            return llm.LLMResult(value=out, route="cloud")

        monkeypatch.setattr(judge_mod, "chat_json", fake)
        check = await evaluate_with_excerpt(
            claim, "r1", pair["excerpt"], pair["title"], "abstract")
    assert check.label == pair["expected"], (
        f"{pair['id']}: got {check.label} ({check.rationale})"
    )
    if check.label in {"supported", "partial", "unsupported"}:
        assert check.evidence_span is not None
        assert check.source_excerpt[check.evidence_span[0]:check.evidence_span[1]]
