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
from citecheck.support.evidence import locate_evidence, locate_spliced, normalize_text
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


def test_locate_evidence_joins_pdf_line_hyphens():
    src = "a benchmark in object category classi- fication and detection"
    span = locate_evidence("object category classification and detection", src)
    assert span is not None
    assert src[span[0]:span[1]] == "object category classi- fication and detection"
    # a hyphen before a capital or digit is real text, never dropped
    assert locate_evidence("Faster RCNN", "Faster R- CNN") is None


def test_locate_evidence_ignores_split_latin_words():
    src = "we investigate the effect of the convolutional n etwork depth on t he accuracy"
    span = locate_evidence("the convolutional network depth on the accuracy", src)
    assert span is not None
    assert src[span[0]:span[1]] == "the convolutional n etwork depth on t he accuracy"
    assert locate_evidence("the convolutional network width", src) is None


def test_locate_spliced_keeps_longest_verbatim_piece():
    src = "We built a corpus. It has many parts. We collected 93k articles from CNN."
    piece, span = locate_spliced("We built a corpus... We collected 93k articles from CNN.", src)
    assert piece == "We collected 93k articles from CNN."
    assert src[span[0]:span[1]] == piece
    # every piece must be in the source, in order
    assert locate_spliced("We collected 93k articles... We built a corpus.", src) is None
    assert locate_spliced("We built a corpus... a sentence not in it", src) is None


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


def test_flattened_table_detection_zh_and_en():
    zh = "任务型对话数据集统计 " + "训练集:13084句 验证集:766句 测试集:1521句 " * 24
    en = "Dialogue dataset statistics " + "train: 13084 validation: 766 test: 1521 " * 20
    assert claims_mod._is_flattened_table(zh)
    assert claims_mod._is_flattened_table(en)


def test_flattened_table_detection_preserves_numeric_prose():
    en = ("The cohort contains 1200 patients: 600 received treatment: "
          "600 received placebo. ") * 10
    zh = ("实验包含1200名受试者：600名接受干预：600名接受安慰剂。"
          "两组在年龄与性别上保持平衡。") * 12
    short_table = "训练集:13084句 验证集:766句 测试集:1521句"
    assert not claims_mod._is_flattened_table(en)
    assert not claims_mod._is_flattened_table(zh)
    assert not claims_mod._is_flattened_table(short_table)


@pytest.mark.asyncio
async def test_extract_skips_flattened_table_without_llm(monkeypatch):
    body = "任务型对话数据集统计 " + "训练集:13084句 验证集:766句 测试集:1521句 " * 24
    text = body + "[29]"
    para = Paragraph(id="p0", section_id="s0", text=text, char_offset=0)
    marker = CitationMarker(
        id="m0", paragraph_id="p0", start=len(body), end=len(text),
        raw="[29]", ref_ids=["r29"],
    )

    async def unexpected(task, messages, schema, **kw):
        raise AssertionError("flattened table must not reach the extract model")

    monkeypatch.setattr(claims_mod, "chat_json", unexpected)
    assert await extract_claims(para, [marker]) == []
    assert para.text == text


@pytest.mark.asyncio
async def test_extract_preserves_prose_in_mixed_table_paragraph(monkeypatch):
    normal = "在实践中经常观察到用户模拟器过拟合[212]."
    table = ("一种方法通过用户目标评估系统"
             + "训练集:13084句 验证集:766句 测试集:1521句 " * 16
             + "[230-231].")
    tail = "另一种方法仍然需要人工评估[232-233].实际上仍需继续评估"
    text = normal + table + tail
    para = Paragraph(id="p0", section_id="s0", text=text, char_offset=0)
    markers = []
    for i, raw in enumerate(["[212]", "[230-231]", "[232-233]"]):
        start = text.index(raw)
        markers.append(CitationMarker(
            id=f"m{i}", paragraph_id="p0", start=start, end=start + len(raw),
            raw=raw, ref_ids=[f"r{i}"],
        ))
    prompts = []

    async def fake(task, messages, schema, **kw):
        prompts.append(messages[0]["content"])
        return llm.LLMResult(value=None, route="local")

    monkeypatch.setattr(claims_mod, "chat_json", fake)
    found = await extract_claims(para, markers)
    assert len(prompts) == 2
    assert all("训练集" not in prompt for prompt in prompts)
    assert len(found) == 2
    assert {c.marker_ids[0] for c in found} == {"m0", "m2"}
    assert para.text == text


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
                                  "marker_ids": ["m1"]}]),  # sentence-local tag
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
                "marker_ids": ["m1", "m99"],  # m99 does not exist
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
async def test_extract_prompt_independent_of_global_marker_ids(monkeypatch):
    """F8: an injected citation earlier in the paper shifted every later
    global marker id, changed every later prompt and missed the cache.
    The model sees sentence-local tags, so the prompt only depends on the
    sentence."""
    text = "Attention helps sequence models [1] here."
    para = Paragraph(id="p0", section_id="s0", text=text, char_offset=0)
    prompts = []

    async def fake(task, messages, schema, **kw):
        prompts.append(messages[0]["content"])
        return llm.LLMResult(value=schema(claims=[{
            "text": "Attention helps sequence models", "marker_ids": ["m1"]}]),
            route="local")

    monkeypatch.setattr(claims_mod, "chat_json", fake)
    out = []
    for mid in ("m0", "m57"):
        m = CitationMarker(id=mid, paragraph_id="p0", start=32, end=35,
                           raw="[1]", ref_ids=["r1"])
        out.append(await extract_claims(para, [m]))
    assert prompts[0] == prompts[1]
    assert out[1][0].marker_ids == ["m57"]


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
async def test_review_reads_expanded_excerpt(monkeypatch):
    """The review judges a larger excerpt ranked on the claim plus search
    terms; its evidence is verified against that excerpt, and co-cited
    entries reach every prompt."""
    prompts, queries = [], []

    async def fake(task, messages, schema, **kw):
        if schema is judge_mod._Terms:
            return llm.LLMResult(value=schema(terms=["attention"]), route="cloud")
        if task == "judge":
            out = JudgeOut(label="partial", evidence="short text", rationale="x")
        else:
            out = JudgeOut(label="supported", evidence="only in the wide text",
                           rationale="y")
        prompts.append((task, messages[0]["content"]))
        return llm.LLMResult(value=out, route="cloud")

    def expand(q):
        queries.append(q)
        return "short text. only in the wide text."

    monkeypatch.setattr(judge_mod, "chat_json", fake)
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=5, text="claim",
                  marker_ids=["m0"])
    check = await evaluate_with_excerpt(
        claim, "r1", "short text", "T", "fulltext",
        cocited=["[2] Other A. Another work"], expand=expand)
    assert check.label == "supported"
    assert check.source_excerpt == "short text. only in the wide text."
    assert queries == ["claim attention"]
    judged = [p for t, p in prompts if t in ("judge", "review")]
    assert len(judged) == 2 and all("[2] Other A. Another work" in p for p in judged)
    assert "only in the wide text" in judged[1] and "only in the wide text" not in judged[0]


@pytest.mark.asyncio
async def test_review_evidence_reask(monkeypatch):
    """Unlocatable review evidence gets the same single re-ask."""
    calls = []

    async def fake(task, messages, schema, **kw):
        calls.append(task)
        ev = "not in source" if len(calls) == 2 else "real source text"
        return llm.LLMResult(
            value=JudgeOut(label="unsupported", evidence=ev, rationale="x"),
            route="cloud",
        )

    monkeypatch.setattr(judge_mod, "chat_json", fake)
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=5, text="claim",
                  marker_ids=["m0"])
    check = await evaluate_with_excerpt(
        claim, "r1", "real source text", "T", "abstract")
    assert calls == ["judge", "review", "review"]
    assert check.label == "unsupported"


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


def test_support_finding_severities():
    from citecheck.parse.parser import ParsedDocument
    from citecheck.schema import Document, SupportCheck
    from citecheck.support.layer import _support_findings

    parsed = ParsedDocument(document=Document())
    claim = Claim(id="c0", paragraph_id="p0", start=0, end=4,
                  text="论断", marker_ids=[])
    labels = [("unsupported", False), ("partial", False),
              ("undetermined", True)]
    checks = [SupportCheck(claim_id="c0", ref_id=f"r{i}", label=lab,
                           source_kind="fulltext", rationale="x",
                           off_topic=ot)
              for i, (lab, ot) in enumerate(labels)]
    jobs = [(claim, c.ref_id) for c in checks]
    sev = [f.severity for f in _support_findings(parsed, jobs, checks)]
    assert sev == ["high", "low", "medium"]


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


# ---------------------------------------------------------------------------
# arXiv abstract fetch: a transient 429 must not be cached as an empty
# abstract for the whole cache TTL — the failure is retried next call

@pytest.mark.asyncio
async def test_arxiv_title_failure_not_cached(tmp_path, monkeypatch):
    from citecheck.cache import Cache
    from citecheck.support import sources as sup

    cache = Cache(tmp_path / "axt.sqlite")
    calls = {"n": 0}
    sleeps: list[float] = []

    async def capture(url, params=None, **kw):
        calls["n"] += 1
        return httpx.Response(429, text="slow down",
                              request=httpx.Request("GET", url))

    async def fake_throttle():
        pass

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(sup, "_arxiv_throttle", fake_throttle)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    client = httpx.AsyncClient()
    monkeypatch.setattr(client, "get", capture)
    try:
        assert await sup._arxiv_title_search("A title", client, cache) is None
        assert calls["n"] == 2            # one retry, then gave up
        assert any(d >= 3.0 for d in sleeps)
        # nothing cached: a later call retries instead of replaying ""
        assert await sup._arxiv_title_search("A title", client, cache) is None
        assert calls["n"] == 4
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_arxiv_title_retry_then_cached(tmp_path, monkeypatch):
    from citecheck.cache import Cache
    from citecheck.support import sources as sup

    cache = Cache(tmp_path / "axt2.sqlite")
    calls = {"n": 0}

    async def capture(url, params=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down",
                                  request=httpx.Request("GET", url))
        body = "<feed><entry><summary> the abstract </summary></entry></feed>"
        return httpx.Response(200, text=body,
                              request=httpx.Request("GET", url))

    async def fake_throttle():
        pass

    async def fake_sleep(d):
        pass

    monkeypatch.setattr(sup, "_arxiv_throttle", fake_throttle)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    client = httpx.AsyncClient()
    monkeypatch.setattr(client, "get", capture)
    try:
        got = await sup._arxiv_title_search("A title", client, cache)
        assert got == "the abstract"
        assert calls["n"] == 2
        # cached now — no further requests
        assert await sup._arxiv_title_search("A title", client, cache) \
            == "the abstract"
        assert calls["n"] == 2
    finally:
        await client.aclose()
