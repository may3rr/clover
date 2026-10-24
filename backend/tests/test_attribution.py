"""Attribution-consistency rule: "X等人[n]" in text vs the first author of
reference [n]. Zero-evidence miscitation signal — deterministic, no model."""

from __future__ import annotations

from types import SimpleNamespace

from citecheck.lint.attribution import check_attribution
from citecheck.schema import CitationMarker, Paragraph, Reference


def _parsed(text: str, ref_authors: list[str], name_hint: str = ""):
    """One paragraph, one marker appended after `name_hint`-agnostic text;
    the marker's offsets are computed from the actual text."""
    label = "5"
    marker_raw = f"[{label}]"
    start = text.index(marker_raw)
    para = Paragraph(id="p1", section_id="s1", text=text, char_offset=0)
    marker = CitationMarker(
        id="m1", paragraph_id="p1", start=start, end=start + len(marker_raw),
        raw=marker_raw, kind="numeric", ref_ids=["r5"])
    ref = Reference(id="r5", raw=f"[{label}] x", authors=ref_authors)
    return SimpleNamespace(paragraphs=[para], markers=[marker],
                           references=[ref])


def test_zh_mismatch_fires():
    p = _parsed("徐增林等人[5]提出了一套知识图谱构建方法。", ["王大明"])
    fs = check_attribution(p)
    assert len(fs) == 1
    assert fs[0].severity == "medium"
    assert fs[0].layer == "support"
    assert fs[0].refs == ["r5"]


def test_zh_match_silent():
    p = _parsed("徐增林等人[5]提出了一套知识图谱构建方法。", ["徐增林", "盛泳潘"])
    assert check_attribution(p) == []


def test_latin_before_dengren_fires():
    p = _parsed("Huang等人[5]提出的FusionNet模型效果好。", ["Talmor A", "Berant J"])
    assert len(check_attribution(p)) == 1


def test_latin_et_al_mismatch_fires():
    p = _parsed("Cheng et al.[5] reported a strong result.", ["Sekine S"])
    assert len(check_attribution(p)) == 1


def test_latin_et_al_match_silent():
    p = _parsed("Cheng et al.[5] reported a strong result.", ["Cheng Wei"])
    assert check_attribution(p) == []


def test_bare_deng_after_zh_noun_skipped():
    # "测试数据等[5]" — 等 = "et cetera", not an attribution
    p = _parsed("本文使用了包括测试数据等[5]多个资源。", ["王大明"])
    assert check_attribution(p) == []


def test_bare_deng_after_latin_fires():
    p = _parsed("Li等[5]提出了新的模型。", ["Wang X"])
    assert len(check_attribution(p)) == 1


def test_multi_author_group_skipped():
    # the captured name is the second author of the group — the first may
    # well be the reference's
    p = _parsed("Bordes和Weston等人[5]提出了模型。", ["Bordes A"])
    assert check_attribution(p) == []


def test_cross_script_skipped():
    p = _parsed("Vaswani等人[5]提出了Transformer。", ["张三"])
    assert check_attribution(p) == []


def test_multi_marker_sentence_skipped():
    text = "Zhang等人[5]扩展了Li等人[6]的早期工作。"
    p1 = Paragraph(id="p1", section_id="s1", text=text, char_offset=0)
    m1 = CitationMarker(id="m1", paragraph_id="p1", start=text.index("[5]"),
                        end=text.index("[5]") + 3, raw="[5]", kind="numeric",
                        ref_ids=["r5"])
    m2 = CitationMarker(id="m2", paragraph_id="p1", start=text.index("[6]"),
                        end=text.index("[6]") + 3, raw="[6]", kind="numeric",
                        ref_ids=["r6"])
    parsed = SimpleNamespace(
        paragraphs=[p1], markers=[m1, m2],
        references=[Reference(id="r5", raw="[5] x", authors=["Wang X"]),
                    Reference(id="r6", raw="[6] x", authors=["Zhao M"])])
    assert check_attribution(parsed) == []


def test_collective_noun_skipped():
    p = _parsed("该方法借鉴了已有方法等人[5]的思路。", ["王大明"])
    assert check_attribution(p) == []
