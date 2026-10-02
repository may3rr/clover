"""Low-level access to word/document.xml — the single source of truth for
paragraph ordering and character offsets.

This module is shared with the export task (T10): the export writer maps
Finding/Revision anchors back to XML through the very same
``paragraph_text_map`` segments, so any change to the text rules below
automatically keeps reading and writing consistent.

Text rules for a paragraph's visible text:
- ``w:t`` contributes its text;
- ``w:tab`` contributes "\\t"; ``w:br`` and ``w:cr`` contribute "\\n";
- text inside ``w:ins`` is included; anything under ``w:del`` /
  ``w:moveFrom`` (incl. ``w:delText``) is excluded;
- field instruction text (``w:instrText``) is excluded, but field result
  runs — the runs between ``separate`` and ``end`` fldChars, and the runs
  inside ``w:fldSimple`` — are included as normal text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def qn(local: str) -> str:
    return f"{{{W_NS}}}{local}"


W_T = qn("t")
W_TAB = qn("tab")
W_BR = qn("br")
W_CR = qn("cr")
W_INSTR = qn("instrText")
W_DEL = qn("del")
W_MOVEFROM = qn("moveFrom")
W_R = qn("r")
W_P = qn("p")
W_BODY = qn("body")
W_FLDCHAR = qn("fldChar")
W_FLDSIMPLE = qn("fldSimple")
W_RPR = qn("rPr")
W_VERTALIGN = qn("vertAlign")
W_PPR = qn("pPr")
W_PSTYLE = qn("pStyle")
W_OUTLINELVL = qn("outlineLvl")
W_VAL = qn("val")
W_FLDCHARTYPE = qn("fldCharType")
W_INSTR_ATTR = qn("instr")

_TEXT_TAGS = {W_T, W_TAB, W_BR, W_CR}
_SKIP_SUBTREES = {W_DEL, W_MOVEFROM}


def _render(el: etree._Element) -> str:
    """Visible text contributed by a single text-bearing element."""
    if el.tag == W_T:
        return el.text or ""
    if el.tag == W_TAB:
        return "\t"
    return "\n"  # w:br, w:cr


def _iter_nodes(el: etree._Element, run: etree._Element | None = None):
    """Yield ``(element, enclosing w:r or None)`` in document order.

    Does not descend into ``w:del`` / ``w:moveFrom`` subtrees, so deleted
    text never reaches callers. Every other element is yielded, including
    container elements, so callers can also observe structure (fldChar,
    instrText, pPr, ...).
    """
    if el.tag == W_R:
        run = el
    yield el, run
    if el.tag in _SKIP_SUBTREES:
        return
    for child in el:
        yield from _iter_nodes(child, run)


@dataclass
class Segment:
    """One contiguous piece of paragraph text produced by one XML node.

    ``node`` is the text-bearing element (w:t / w:tab / w:br / w:cr),
    ``run`` is its enclosing w:r (or None), ``start`` is the offset of this
    segment inside the paragraph's text, and ``end`` is ``start + len(text)``.
    Export code uses (node, run, start, end) to split runs at anchor
    boundaries without recomputing offsets.
    """

    node: etree._Element
    run: etree._Element | None
    start: int
    text: str

    @property
    def end(self) -> int:
        return self.start + len(self.text)


@dataclass
class FieldResult:
    """A field (complex or simple) inside a paragraph.

    ``instr`` is the field instruction (e.g. ``ZOTERO_ITEM CSL_CITATION {...}``),
    ``span`` is the (start, end) of the visible result text inside the
    paragraph text, or None when the field has no result.
    """

    instr: str
    span: tuple[int, int] | None


def iter_paragraphs(root: etree._Element) -> Iterator[tuple[str, etree._Element]]:
    """Yield ``(id, w:p)`` for every paragraph under w:body, in document
    order, including paragraphs inside table cells. Ids are p0, p1, ...

    ``root`` may be the w:document element or w:body itself.
    """
    body = root if root.tag == W_BODY else root.find(qn("body"))
    if body is None:
        return
    for i, p in enumerate(body.iter(W_P)):
        yield f"p{i}", p


def paragraph_text_map(p: etree._Element) -> tuple[str, list[Segment]]:
    """Return ``(text, segments)`` for a w:p element.

    ``text`` is the paragraph's visible text under the module-level rules;
    ``segments`` maps that text back to XML nodes and runs, in order.
    """
    parts: list[str] = []
    segments: list[Segment] = []
    cursor = 0
    for el, run in _iter_nodes(p):
        if el.tag in _TEXT_TAGS:
            s = _render(el)
            if s:
                segments.append(Segment(node=el, run=run, start=cursor, text=s))
                parts.append(s)
                cursor += len(s)
    return "".join(parts), segments


@dataclass
class _FieldCtx:
    instr: str = ""
    result_start: int | None = None
    result_end: int | None = None


def paragraph_fields(p: etree._Element) -> list[FieldResult]:
    """Complex fields (fldChar begin/instrText/separate/result/end) in a
    paragraph. ``instrText`` never contributes to paragraph text, so the
    spans line up with ``paragraph_text_map`` offsets.
    """
    fields: list[FieldResult] = []
    stack: list[_FieldCtx] = []
    cursor = 0
    for el, _run in _iter_nodes(p):
        tag = el.tag
        if tag == W_FLDCHAR:
            kind = el.get(W_FLDCHARTYPE)
            if kind == "begin":
                stack.append(_FieldCtx())
            elif kind == "separate" and stack:
                stack[-1].result_start = cursor
            elif kind == "end" and stack:
                ctx = stack.pop()
                span = None
                if ctx.result_start is not None:
                    span = (ctx.result_start, cursor)
                fields.append(FieldResult(instr=ctx.instr.strip(), span=span))
        elif tag == W_INSTR:
            if stack:
                stack[-1].instr += el.text or ""
        elif tag in _TEXT_TAGS:
            cursor += len(_render(el))
    return fields


def fldsimple_fields(
    p: etree._Element, segments: list[Segment]
) -> list[FieldResult]:
    """Simple fields (w:fldSimple): instruction lives in the w:instr
    attribute, result text is the element's inner runs."""
    start_by_node = {id(s.node): s.start for s in segments}
    end_by_node = {id(s.node): s.end for s in segments}
    out: list[FieldResult] = []
    for el in p.iter(W_FLDSIMPLE):
        instr = (el.get(W_INSTR_ATTR) or "").strip()
        starts = [start_by_node[id(t)] for t in el.iter() if id(t) in start_by_node]
        ends = [end_by_node[id(t)] for t in el.iter() if id(t) in end_by_node]
        span = (min(starts), max(ends)) if starts else None
        out.append(FieldResult(instr=instr, span=span))
    return out


def is_superscript_run(run: etree._Element | None) -> bool:
    if run is None:
        return False
    rpr = run.find(W_RPR)
    if rpr is None:
        return False
    va = rpr.find(W_VERTALIGN)
    return va is not None and va.get(W_VAL) == "superscript"


def paragraph_style_id(p: etree._Element) -> str | None:
    ppr = p.find(W_PPR)
    if ppr is None:
        return None
    pstyle = ppr.find(W_PSTYLE)
    if pstyle is None:
        return None
    return pstyle.get(W_VAL)


def paragraph_outline_lvl(p: etree._Element) -> int | None:
    ppr = p.find(W_PPR)
    if ppr is None:
        return None
    ol = ppr.find(W_OUTLINELVL)
    if ol is None:
        return None
    try:
        return int(ol.get(W_VAL, ""))
    except ValueError:
        return None
