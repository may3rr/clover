"""T1 robustness tests: auto-numbering, footnotes, degraded docs and the
LLM-assisted bibliography boundary."""

import asyncio
from pathlib import Path

import pytest
from docx import Document
from lxml import etree

from citecheck.lint.norms import check_norms
from citecheck.lint.reorder import plan_reorder
from citecheck.parse import bibguess
from citecheck.parse.numbering import (
    format_counter,
    load_numbering,
    paragraph_prefixes,
    to_roman,
)
from citecheck.parse.parser import (
    ParsedDocument,
    apply_bibliography_start,
    parse_docx,
)
from citecheck.parse import docx_xml as dx
from citecheck.parse import headings as hd

FIXTURES = Path(__file__).parent / "fixtures"
W = dx.W_NS


def w(tag):
    return f"{{{W}}}{tag}"


# ------------------------------------------------------------- numbering


def test_numbering_counters_and_formats():
    assert to_roman(4) == "iv"
    assert to_roman(0) == "0"
    assert format_counter(3, "decimal") == "3"
    assert format_counter(3, "decimalZero") == "03"
    assert format_counter(28, "lowerLetter") == "ab"
    assert format_counter(14, "upperRoman") == "XIV"


def _numbering_doc(tmp_path, lvl_text="[%1]", fmt="decimal", start=1):
    """Build a docx whose paragraphs are numbered by a real
    numbering.xml (two heading refs + two list items)."""
    doc = Document()
    ps = [doc.add_paragraph(t) for t in
          ("First heading", "body text", "second heading", "item a",
           "item b")]
    nsdecl = f'xmlns:w="{W}"'
    numxml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:numbering {nsdecl}>'
        f'<w:abstractNum {nsdecl} w:abstractNumId="77">'
        f'<w:lvl w:ilvl="0"><w:start w:val="{start}"/>'
        f'<w:numFmt w:val="{fmt}"/><w:lvlText w:val="{lvl_text}"/>'
        f'<w:suff w:val="space"/></w:lvl>'
        f'<w:lvl w:ilvl="1"><w:start w:val="1"/>'
        f'<w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2."/>'
        f'<w:suff w:val="space"/></w:lvl>'
        "</w:abstractNum>"
        f'<w:num {nsdecl} w:numId="77"><w:abstractNumId w:val="77"/></w:num>'
        "</w:numbering>")
    from tests.fixtures.make_fixtures import _rewrite_zip
    for i, p in enumerate(ps):
        ilvl = 1 if i == 1 else 0  # "body text" is a level-2 item
        ppr = p._p.get_or_add_pPr()
        ppr.append(etree.fromstring(
            f'<w:numPr {nsdecl}><w:ilvl w:val="{ilvl}"/>'
            f'<w:numId w:val="77"/></w:numPr>'))
    out = tmp_path / "num.docx"
    doc.save(out)
    # replace the template numbering part wholesale
    _rewrite_zip(out, {"word/numbering.xml": numxml.encode()})
    return out


def test_paragraph_prefixes_restart_and_levels(tmp_path):
    path = _numbering_doc(tmp_path)
    import zipfile
    with zipfile.ZipFile(path) as zf:
        root = etree.fromstring(zf.read("word/document.xml"))
        num_root = etree.fromstring(zf.read("word/numbering.xml"))
    p_elems = [p for _, p in dx.iter_paragraphs(root)]
    numbering = load_numbering(num_root)
    prefixes = paragraph_prefixes(p_elems, numbering, {})
    # level-1 item between the two level-0 items must not restart the
    # level-0 counter, and renders "2.1." via the %1.%2 template
    assert prefixes == ["[1] ", "1.1. ", "[2] ", "[3] ", "[4] "]


def test_autonum_refs_are_reordered_as_moves_only():
    """Auto-numbered refs: reorder must emit paragraph MOVES whose old/new
    texts are identical (Word renumbers) — never an in-place label edit
    that would target virtual digits."""
    doc = parse_docx(FIXTURES / "autonum_refs.docx")
    # build a marker order different from list order: cite r3 first?
    # the fixture cites 1,2,3,4 in order, so force a reorder by hand
    doc.markers[0].ref_ids = ["r3"]  # pretend [1] actually means r3
    revs = plan_reorder(doc)
    inplace = [r for r in revs
               if r.kind == "ref_reorder" and r.move_after is None]
    assert not inplace  # no label edits on virtual numbering
    moves = [r for r in revs if r.kind == "ref_reorder" and r.move_after]
    for r in moves:
        assert r.old == r.new  # label never rewritten literally
    # literal markers still renumber to track the reordered list
    assert any(r.kind == "marker_renumber" for r in revs)


# ------------------------------------------------------------- footnotes


def test_footnote_markers_have_real_spans():
    doc = parse_docx(FIXTURES / "footnote_cites.docx")
    paras = {p.id: p for p in doc.paragraphs}
    for m in doc.markers:
        assert m.kind == "footnote"
        assert paras[m.paragraph_id].text[m.start:m.end] == m.raw
        assert m.raw.strip()


def test_footnote_refs_excluded_from_reorder():
    doc = parse_docx(FIXTURES / "footnote_cites.docx")
    assert [r.origin for r in doc.references] == ["footnote"] * 4
    assert plan_reorder(doc) == []


# ------------------------------------------------- degraded empty docs


def _plain_doc(tmp_path, texts=("A plain paragraph with no citations.",
                                "Another paragraph of plain prose.")):
    doc = Document()
    for t in texts:
        doc.add_paragraph(t)
    out = tmp_path / "plain.docx"
    doc.save(out)
    return out


def test_empty_document_reports_honestly(tmp_path):
    doc = parse_docx(_plain_doc(tmp_path))
    assert not doc.markers and not doc.references
    findings = check_norms(doc)
    assert any("找到引用标记和参考文献列表" in f.title for f in findings)


def test_distribution_silent_on_empty_doc(tmp_path):
    from citecheck.distribution.layer import run_distribution
    doc = parse_docx(_plain_doc(tmp_path))
    _dist, findings = asyncio.run(
        run_distribution(doc, classify=False))
    assert findings == []


# ----------------------------------------- llm-assisted boundary (T1e)


def _bibliography_doc(tmp_path):
    """A doc whose bibliography has NO heading and NO numbering — the
    deterministic detectors must miss it so the LLM path is exercised."""
    doc = Document()
    doc.add_paragraph("Boundary Test Manuscript")
    doc.add_paragraph("Attention models [1] dominate the field and "
                      "dense retrieval [2] is standard.")
    doc.add_paragraph(
        "Vaswani A, Shazeer N, Parmar N, et al. Attention is all you "
        "need. NeurIPS 2017.")
    doc.add_paragraph(
        "Karpukhin V, Oguz B, Min S, et al. Dense passage retrieval for "
        "open-domain question answering. EMNLP 2020.")
    doc.add_paragraph(
        "Lewis P, Perez E, Piktus A, et al. Retrieval-augmented "
        "generation for knowledge-intensive NLP tasks. NeurIPS 2020.")
    out = tmp_path / "bibguess.docx"
    doc.save(out)
    return out


class _FakeOut:
    def __init__(self, start):
        self.start = start


class _FakeRes:
    def __init__(self, value):
        self.value = value


def test_bibguess_accept_and_apply(tmp_path, monkeypatch):
    path = _bibliography_doc(tmp_path)
    doc = parse_docx(path)
    assert not doc.references  # deterministic paths all failed

    async def fake(task, messages, schema, **kw):
        return _FakeRes(_FakeOut(2))
    monkeypatch.setattr(bibguess, "chat_json", fake)

    start = asyncio.run(bibguess.guess_bibliography_start(doc))
    assert start == 2
    added = apply_bibliography_start(doc, start)
    assert added == 3
    assert len(doc.references) == 3
    m = {m.raw: m.ref_ids for m in doc.markers}
    assert m["[1]"] == ["r1"] and m["[2]"] == ["r2"]


def test_bibguess_rejects_unverifiable_span(tmp_path, monkeypatch):
    path = _bibliography_doc(tmp_path)
    doc = parse_docx(path)

    async def fake(task, messages, schema, **kw):
        return _FakeRes(_FakeOut(0))  # claims the prose starts the bib
    monkeypatch.setattr(bibguess, "chat_json", fake)
    assert asyncio.run(bibguess.guess_bibliography_start(doc)) is None

    async def fake2(task, messages, schema, **kw):
        return _FakeRes(_FakeOut(None))
    monkeypatch.setattr(bibguess, "chat_json", fake2)
    assert asyncio.run(bibguess.guess_bibliography_start(doc)) is None
