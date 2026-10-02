"""T3 tests: evidence verbatim check, claim extraction, judge accuracy.

The 10 claim–source pairs live in tests/fixtures/llm/support_pairs.json.
Default run replays recorded Qwen responses; CITECHECK_LIVE=1 calls the
real model (and record_llm.py refreshes the recording).
"""

import json
import os
from pathlib import Path

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
        text="Transformers work well [1] on many tasks.", char_offset=0,
    )
    marker = CitationMarker(
        id="m0", paragraph_id="p0", start=23, end=26, raw="[1]", ref_ids=["r1"]
    )

    async def fake(task, messages, schema, **kw):
        return llm.LLMResult(
            value=schema(claims=[{"text": "Transformers work well",
                                  "marker_ids": ["m0"]}]),
            route="local",
        )

    monkeypatch.setattr(claims_mod, "chat_json", fake)
    claims = await extract_claims(para, [marker])
    assert len(claims) == 1
    c = claims[0]
    assert para.text[c.start : c.end] == "Transformers work well"
    assert c.marker_ids == ["m0"]


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

    async def good_cloud(model, messages):
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
