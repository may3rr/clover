"""T5 lint tests: norms, reorder, typos."""

from __future__ import annotations

import pytest

from citecheck.lint import typos as typo_mod
from citecheck.lint.norms import check_norms
from citecheck.lint.reorder import _format_marker, plan_reorder
from citecheck.llm.client import LLMResult
from citecheck.parse.links import _numeric_items
from citecheck.parse.parser import ParsedDocument, parse_docx
from citecheck.refs.structure import parse_reference
from citecheck.schema import (
    Anchor,
    CitationMarker,
    Document,
    Paragraph,
    Reference,
    Section,
)

FIXTURES = "tests/fixtures"


def mk_parsed(
    texts: list[str],
    refs: list[str],
    markers: list[tuple[int, str, str, list[int]]],
    *,
    style: str = "numeric",
    managed_by: str | None = None,
) -> ParsedDocument:
    """Build a minimal ParsedDocument. markers: (para_idx, raw, kind,
    resolved ref numbers). Reference list paragraphs are appended after
    ``texts``."""
    n_body = len(texts)
    all_texts = texts + refs
    paragraphs = [
        Paragraph(id=f"p{i}", section_id="s0", text=t, char_offset=0)
        for i, t in enumerate(all_texts)
    ]
    references = []
    for i, t in enumerate(refs):
        info = parse_reference(t)
        references.append(Reference(
            id=f"r{i + 1}", raw=t, paragraph_id=f"p{n_body + i}",
            title=info["title"], authors=info["authors"], year=info["year"],
            venue=info["venue"], doi=info["doi"], lang=info["lang"],
            label=info["label"] or str(i + 1)))

    out_markers = []
    for k, (pi, raw, kind, nums) in enumerate(markers):
        start = all_texts[pi].index(raw)
        out_markers.append(CitationMarker(
            id=f"m{k}", paragraph_id=f"p{pi}", start=start,
            end=start + len(raw), raw=raw, kind=kind,  # type: ignore[arg-type]
            ref_ids=[f"r{n}" for n in nums],
        ))
    return ParsedDocument(
        document=Document(citation_style=style, managed_by=managed_by),  # type: ignore[arg-type]
        sections=[Section(id="s0", title="H", canonical="intro",
                          heading_paragraph_id="p0")],
        paragraphs=paragraphs, markers=out_markers, references=references,
    )


def titles(findings) -> list[str]:
    return [f.title for f in findings]


# ---------------------------------------------------------------- norms


def test_norms_uncited_positive():
    p = mk_parsed(["See [1]."], ["[1] A. X. Foo.", "[2] B. Y. Bar."],
                  [(0, "[1]", "numeric", [1])])
    f = [x for x in check_norms(p) if x.title == "这篇参考文献在正文中没有被引用"]
    assert len(f) == 1 and f[0].refs == ["r2"] and f[0].severity == "medium"
    assert f[0].anchor and f[0].anchor.paragraph_id == "p2"


def test_norms_uncited_negative():
    p = mk_parsed(["See [1] and [2]."], ["[1] A.", "[2] B."],
                  [(0, "[1]", "numeric", [1]), (0, "[2]", "numeric", [2])])
    assert "这篇参考文献在正文中没有被引用" not in titles(check_norms(p))


def test_norms_unresolved_marker_positive():
    p = mk_parsed(["As shown [17]."], ["[1] A.", "[2] B.", "[3] C."],
                  [(0, "[17]", "numeric", [])])
    f = [x for x in check_norms(p)
         if x.title == "正文引用找不到对应的参考文献条目"]
    assert len(f) == 1 and f[0].severity == "high"
    assert f[0].anchor and f[0].anchor.start == 9 and f[0].anchor.end == 13


def test_norms_unresolved_range_partial():
    # "[2,9]" partly resolves: 9 is out of range
    p = mk_parsed(["Text [2,9]."], ["[1] A.", "[2] B.", "[3] C."],
                  [(0, "[2,9]", "numeric", [2])])
    f = [x for x in check_norms(p)
         if x.title == "正文引用找不到对应的参考文献条目"]
    assert len(f) == 1 and "9" in f[0].detail


def test_norms_unresolved_negative():
    p = mk_parsed(["Text [1,2]."], ["[1] A.", "[2] B."],
                  [(0, "[1,2]", "numeric", [1, 2])])
    assert check_norms(p) == []


def test_norms_duplicate_positive():
    refs = [
        "[1] Devlin J. BERT: Pre-training of deep bidirectional transformers "
        "for language understanding. NAACL 2019.",
        "[2] Devlin J, Chang M. BERT: pre-training of deep bidirectional "
        "transformers for language understanding. NAACL-HLT 2019.",
    ]
    p = mk_parsed(["Cited [1,2]."], refs, [(0, "[1,2]", "numeric", [1, 2])])
    f = [x for x in check_norms(p) if x.title == "这条参考文献与前面的条目重复"]
    assert len(f) == 1 and f[0].refs == ["r1", "r2"]


def test_norms_duplicate_negative():
    refs = [
        "[1] Devlin J. BERT: Pre-training of deep bidirectional transformers "
        "for language understanding. NAACL 2019.",
        "[2] Brown T. Language models are few-shot learners. NeurIPS 2020.",
    ]
    p = mk_parsed(["Cited [1,2]."], refs, [(0, "[1,2]", "numeric", [1, 2])])
    assert "这条参考文献与前面的条目重复" not in titles(check_norms(p))


def test_norms_mixed_style_positive():
    p = mk_parsed(["Text [1] and (Xu, 2020)."], ["[1] A."],
                  [(0, "[1]", "numeric", [1]),
                   (0, "(Xu, 2020)", "author_year", [])],
                  style="mixed")
    f = [x for x in check_norms(p) if "混用" in x.title]
    assert len(f) == 1 and f[0].severity == "medium"


def test_norms_mixed_style_negative():
    p = mk_parsed(["Text [1]."], ["[1] A."], [(0, "[1]", "numeric", [1])])
    assert not any("混用" in t for t in titles(check_norms(p)))


def test_norms_gbt_tags_positive():
    refs = [
        "[1] 刘知远, 孙茂松. 知识表示学习研究进展[J]. 计算机研究与发展, 2016.",
        "[2] Smith J. Some English title without a tag. Journal, 2020.",
    ]
    p = mk_parsed(["Text [1,2]."], refs, [(0, "[1,2]", "numeric", [1, 2])])
    f = [x for x in check_norms(p) if x.title == "这条参考文献缺少文献类型标识"]
    assert len(f) == 1 and f[0].refs == ["r2"] and f[0].severity == "low"


def test_norms_gbt_tags_negative():
    refs = [
        "[1] 刘知远. 知识表示学习研究进展[J]. 计算机研究与发展, 2016.",
        "[2] 宗成庆. 统计自然语言处理[M]. 北京: 清华大学出版社, 2013.",
    ]
    p = mk_parsed(["Text [1,2]."], refs, [(0, "[1,2]", "numeric", [1, 2])])
    assert not any("类型标识" in t for t in titles(check_norms(p)))


def test_norms_managed_out_of_order_finding():
    # zotero-managed, refs listed out of first-appearance order
    p = mk_parsed(["See (1) then (2)."], ["[1] A.", "[2] B."],
                  [(0, "(2)", "zotero", [2]), (0, "(1)", "zotero", [1])],
                  managed_by="zotero")
    f = check_norms(p)
    assert any("Zotero" in x.title and "刷新排序" in x.title for x in f)
    # and no revisions are produced for managed docs
    assert plan_reorder(p) == []


def test_norms_managed_in_order_no_finding():
    p = mk_parsed(["See (1) then (2)."], ["[1] A.", "[2] B."],
                  [(0, "(1)", "zotero", [1]), (0, "(2)", "zotero", [2])],
                  managed_by="zotero")
    assert not any("Zotero" in t for t in titles(check_norms(p)))


# ------------------------------------------------------- marker renumber


@pytest.mark.parametrize("raw,nums,expected", [
    ("[1,2,3]", [1, 2, 3], "[1-3]"),       # run of 3 collapses
    ("[2-5]", [2, 3, 4, 7], "[2-4,7]"),    # PLAN example
    ("[1,2]", [1, 2], "[1,2]"),            # run of 2 stays comma-joined
    ("[1,3,4,5,9]", [1, 3, 4, 5, 9], "[1,3-5,9]"),
    ("［2，4-5］", [1, 2, 3], "［1-3］"),    # fullwidth brackets + comma
    ("(3, 4, 5)", [2, 3, 4], "(2-4)"),     # parens, space separator
    ("8", [7], "7"),                        # bracket-less superscript form
])
def test_format_marker(raw, nums, expected):
    assert _format_marker(raw, nums) == expected


def test_format_marker_preserves_separator_spacing():
    assert _format_marker("[1, 3]", [2, 5]) == "[2, 5]"
    assert _format_marker("[1,3]", [2, 5]) == "[2,5]"


# --------------------------------------------------------------- reorder


def apply_reorder(p: ParsedDocument, revs):
    """Apply revisions with T10 semantics: moved entries processed in
    emitted (target) order, each inserted after its move_after element."""
    texts = {x.id: x.text for x in p.paragraphs}
    order = [r.paragraph_id for r in p.references]
    moves = [r for r in revs if r.kind == "ref_reorder" and r.move_after]
    edits = [r for r in revs if r.kind == "ref_reorder" and r.move_after is None]
    for r in moves:
        order.remove(r.anchor.paragraph_id)
        if r.move_after == "__start__":
            order.insert(0, r.anchor.paragraph_id)
        else:
            order.insert(order.index(r.move_after) + 1, r.anchor.paragraph_id)
        texts[r.anchor.paragraph_id] = r.new
    for r in edits:
        t = texts[r.anchor.paragraph_id]
        texts[r.anchor.paragraph_id] = t[: r.anchor.start] + r.new + t[r.anchor.end:]
    for r in revs:
        if r.kind == "marker_renumber":
            t = texts[r.anchor.paragraph_id]
            texts[r.anchor.paragraph_id] = (
                t[: r.anchor.start] + r.new + t[r.anchor.end:])
    return order, texts


def test_reorder_unordered_fixture_end_to_end():
    p = parse_docx(f"{FIXTURES}/numeric_unordered_en.docx")
    revs = plan_reorder(p)
    assert any(r.kind == "marker_renumber" for r in revs)
    assert any(r.move_after == "__start__" for r in revs)

    order, texts = apply_reorder(p, revs)
    para_ref = {r.paragraph_id: r.id for r in p.references}
    final_ref_order = [para_ref[pid] for pid in order]

    # final order == first-appearance order (uncited r3 stays last)
    first_seen: list[str] = []
    for m in p.markers:
        for rid in m.ref_ids:
            if rid not in first_seen:
                first_seen.append(rid)
    first_seen += [r.id for r in p.references if r.id not in first_seen]
    assert final_ref_order == first_seen == ["r5", "r2", "r4", "r1", "r6", "r3"]

    # consecutive labels after applying edits
    for i, pid in enumerate(order):
        assert texts[pid].startswith(f"[{i + 1}]")

    # every renumbered marker resolves to the same ref set as before
    for m in p.markers:
        new_nums = _numeric_items(texts[m.paragraph_id][m.start:m.end])
        assert {final_ref_order[n - 1] for n in new_nums} == set(m.ref_ids)


def test_reorder_already_ordered_no_revisions():
    p = parse_docx(f"{FIXTURES}/gbt_zh.docx")
    assert plan_reorder(p) == []


def test_reorder_zotero_no_revisions():
    p = parse_docx(f"{FIXTURES}/zotero_numeric.docx")
    assert not any(
        r.kind in {"ref_reorder", "marker_renumber"} for r in plan_reorder(p))


def test_reorder_authoryear_unsorted():
    refs = [
        "Vaswani, A. (2017). Attention is all you need. NeurIPS.",
        "Devlin, J. (2019). BERT. NAACL.",
        "Brown, T. (2020). Language models are few-shot learners. NeurIPS.",
    ]
    p = mk_parsed(
        ["Text (Vaswani, 2017)."], refs,
        [(0, "(Vaswani, 2017)", "author_year", [1])],
        style="author_year",
    )
    # strip numeric labels so refs have no literal label
    for r in p.references:
        r.label = None
    revs = plan_reorder(p)
    moves = [r for r in revs if r.move_after]
    order, _ = apply_reorder(p, revs)
    para_ref = {r.paragraph_id: r.id for r in p.references}
    assert [para_ref[x] for x in order] == ["r3", "r2", "r1"]  # B < D < V
    assert moves and all(r.old == r.new for r in moves)  # no label edits


def test_reorder_authoryear_sorted_no_revisions():
    refs = [
        "Brown, T. (2020). Language models are few-shot learners. NeurIPS.",
        "Devlin, J. (2019). BERT. NAACL.",
        "Vaswani, A. (2017). Attention is all you need. NeurIPS.",
    ]
    p = mk_parsed(
        ["Text (Vaswani, 2017)."], refs,
        [(0, "(Vaswani, 2017)", "author_year", [1])],
        style="author_year",
    )
    for r in p.references:
        r.label = None
    assert plan_reorder(p) == []


def test_reorder_authoryear_zh_first_accepted():
    refs = [
        "刘知远, 孙茂松. 知识表示学习研究进展. 计算机研究与发展, 2016.",
        "宗成庆. 统计自然语言处理. 北京: 清华大学出版社, 2013.",
        "Vaswani, A. (2017). Attention is all you need. NeurIPS.",
    ]
    p = mk_parsed(["Text (刘知远, 2016)."], refs,
                  [(0, "(刘知远, 2016)", "author_year", [1])],
                  style="author_year")
    for r in p.references:
        r.label = None
    assert plan_reorder(p) == []  # zh-before-en is acceptable


# ---------------------------------------------------------------- typos


class _FakeLLM:
    def __init__(self, out):
        self.out = out
        self.calls = 0

    async def __call__(self, task, messages, schema, *, route="auto"):
        self.calls += 1
        return LLMResult(value=schema.model_validate(self.out), route="cloud")


async def _run_typos(p: ParsedDocument, out):
    fake = _FakeLLM(out)
    orig = typo_mod.chat_json
    typo_mod.chat_json = fake
    try:
        return await typo_mod.check_typos(p)
    finally:
        typo_mod.chat_json = orig


def _typo_doc(texts: list[str]) -> ParsedDocument:
    return ParsedDocument(
        document=Document(citation_style="numeric"),
        sections=[Section(id="s0", title="", canonical="other")],
        paragraphs=[Paragraph(id=f"p{i}", section_id="s0", text=t,
                              char_offset=0) for i, t in enumerate(texts)],
    )


@pytest.mark.asyncio
async def test_typos_simple_revision():
    p = _typo_doc(["自然语言处理是当前最活跃的的领域之一。"])
    f, revs = await _run_typos(p, {"items": [{
        "original": "活跃的的领域", "correction": "活跃的领域",
        "reason": "叠字"}]})
    assert f == []
    assert len(revs) == 1
    r = revs[0]
    assert r.kind == "typo" and r.old == "的" and r.new == ""
    assert p.paragraphs[0].text[r.anchor.start:r.anchor.end] == "的"


@pytest.mark.asyncio
async def test_typos_big_rewrite_becomes_finding():
    p = _typo_doc(["The quik brown fox jumps over the lazy dog daily."])
    f, revs = await _run_typos(p, {"items": [{
        "original": "quik brown fox jumps",
        "correction": "agile auburn fox leaps gracefully",
        "reason": "rewrite"}]})
    assert revs == []
    assert len(f) == 1 and f[0].title == "疑似笔误，请确认"
    assert "agile auburn fox" in f[0].detail


@pytest.mark.asyncio
async def test_typos_nonunique_and_absent_dropped():
    p = _typo_doc(["的了笔误可能重复的了出现，这段文字足够长用于测试。"])
    f, revs = await _run_typos(p, {"items": [
        {"original": "的了", "correction": "的", "reason": "非唯一"},
        {"original": "不在文中", "correction": "在文中", "reason": "缺失"},
    ]})
    assert f == [] and revs == []


@pytest.mark.asyncio
async def test_typos_marker_overlap_dropped():
    p = _typo_doc(["已有方法 [12] 表明这条路线可行，值得继续研究。"])
    p.markers.append(CitationMarker(
        id="m0", paragraph_id="p0", start=5, end=9, raw="[12]",
        kind="numeric", ref_ids=["r1"]))
    f, revs = await _run_typos(p, {"items": [{
        "original": "方法 [12]", "correction": "方法[12]", "reason": "空格"}]})
    assert f == [] and revs == []


@pytest.mark.asyncio
async def test_typos_digit_change_dropped():
    p = _typo_doc(["模型在2020年达到最好水平，之后逐年提升。"])
    f, revs = await _run_typos(p, {"items": [{
        "original": "在2020年", "correction": "在2021年", "reason": "x"}]})
    assert f == [] and revs == []


@pytest.mark.asyncio
async def test_typos_latin_whole_word():
    p = _typo_doc(["The teh result is stable across seeds and benchmarks."])
    f, revs = await _run_typos(p, {"items": [{
        "original": "The teh result", "correction": "The the result",
        "reason": "拼写"}]})
    assert len(revs) == 1 and revs[0].old == "teh" and revs[0].new == "the"


@pytest.mark.asyncio
async def test_typos_skips_ref_and_short_paragraphs():
    p = _typo_doc(["短.", "这是一个足够长的段落用于测试错别字检查逻辑。"])
    p.references.append(Reference(id="r1", raw="x", paragraph_id="p0"))
    f, revs = await _run_typos(p, {"items": []})
    assert f == [] and revs == []
