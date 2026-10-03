"""Orchestrates docx parsing: paragraphs -> sections -> reference list ->
markers -> linking -> Document metadata.

Public entry: ``parse_docx(path) -> ParsedDocument``. The input file is
opened read-only and never modified.

Beyond literal text, the paragraph text map includes VIRTUAL spans so
downstream layers see what a Word user sees (docx_xml.py keeps them
marked ``Segment.virtual``):
- auto-numbering labels resolved through word/numbering.xml
  (``numbering.paragraph_prefixes``) — "[1] ", "1. ", "3.2 ";
- footnote/endnote reference marks (``notes.paragraph_note_refs``),
  which also produce ``kind="footnote"`` markers; note bodies that look
  like cited sources become ``Reference(origin="footnote")`` entries
  anchored at their citing paragraph.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree
from pydantic import BaseModel, Field

from ..refs.structure import parse_reference
from ..schema import CitationMarker, Document, Paragraph, Reference, Section
from . import docx_xml as dx
from . import headings as hd
from . import notes as nt
from .links import link_markers
from .markers import DetectedMarker, detect_markers
from .numbering import load_numbering, paragraph_prefixes

_ZIP_DOC = "word/document.xml"
_ZIP_STYLES = "word/styles.xml"
_ZIP_NUMBERING = "word/numbering.xml"
_ZIP_CORE = "docProps/core.xml"
_DC_TITLE = "{http://purl.org/dc/elements/1.1/}title"
_CITE_LABEL_RE = re.compile(r"^\s*[\[\(（【]?\d{1,3}[\]\)）】]?[\.、]?\s+\S")


class ParsedDocument(BaseModel):
    """Everything the downstream layers and the docx exporter need."""

    document: Document
    sections: list[Section] = Field(default_factory=list)
    paragraphs: list[Paragraph] = Field(default_factory=list)
    markers: list[CitationMarker] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    # pid -> auto-numbering label prepended to the paragraph text ("" /
    # absent = none). Downstream edits must not treat these virtual
    # labels as literal text — Word renumbers them on its own.
    auto_labels: dict[str, str] = Field(default_factory=dict)


def _read_part(zf: zipfile.ZipFile, name: str) -> etree._Element | None:
    try:
        data = zf.read(name)
    except KeyError:
        return None
    return etree.fromstring(data)


def _core_title(zf: zipfile.ZipFile) -> str | None:
    core = _read_part(zf, _ZIP_CORE)
    if core is None:
        return None
    el = core.find(_DC_TITLE)
    if el is not None and el.text and el.text.strip():
        return el.text.strip()
    return None


def _find_ref_span(
    p_elems: list[etree._Element],
    texts: list[str],
    heading_levels: list[int | None],
) -> tuple[int, int] | None:
    """(start, end) paragraph indices of the reference list, or None."""
    for i, (p, t) in enumerate(zip(p_elems, texts)):
        lvl = heading_levels[i]
        if lvl is not None and hd.is_ref_heading(t):
            end = len(p_elems)
            for j in range(i + 1, len(p_elems)):
                if heading_levels[j] is not None:
                    end = j
                    break
            return i + 1, end
    # no heading: a ZOTERO_BIBL field marks the bibliography
    for i, p in enumerate(p_elems):
        for f in dx.paragraph_fields(p):
            if "ZOTERO_BIBL" in f.instr:
                return i, len(p_elems)
        for el in p.iter(dx.W_FLDSIMPLE):
            if "ZOTERO_BIBL" in (el.get(dx.W_INSTR_ATTR) or ""):
                return i, len(p_elems)
    # last resort: a trailing run of numbered-entry paragraphs (literal
    # "[1] " labels AND virtual auto-numbering labels both match)
    tail = len(texts)
    while tail > 0 and _CITE_LABEL_RE.match(texts[tail - 1].strip()):
        tail -= 1
    if len(texts) - tail >= 3:
        return tail, len(texts)
    return None


def _classify_marker_style(m: DetectedMarker) -> str:
    if m.kind in {"numeric", "superscript", "footnote"}:
        return "numeric"
    if m.kind == "author_year":
        return "author_year"
    # field-managed: judge by the visible result text
    if re.match(r"^\s*[\[\(【（［]?\d", m.raw):
        return "numeric"
    return "author_year"


def _list_reference(idx: int, para_id: str, text: str) -> Reference:
    info = parse_reference(text)
    return Reference(
        id=f"r{idx}",
        raw=text.strip(),
        title=info["title"],
        authors=info["authors"],
        year=info["year"],
        venue=info["venue"],
        doi=info["doi"],
        lang=info["lang"],
        paragraph_id=para_id,
        label=info["label"],
        origin="list",
    )


def parse_docx(path: str | Path) -> ParsedDocument:
    path = Path(path)
    with zipfile.ZipFile(path) as zf:
        root = _read_part(zf, _ZIP_DOC)
        if root is None:
            raise ValueError(f"{path.name}: word/document.xml not found")
        styles_root = _read_part(zf, _ZIP_STYLES)
        numbering_root = _read_part(zf, _ZIP_NUMBERING)
        styles = hd.load_styles(styles_root)
        numbering = load_numbering(numbering_root)
        note_bodies = nt.load_note_bodies(zf)
        core_title = _core_title(zf)

    p_elems: list[etree._Element] = []
    p_ids: list[str] = []
    for pid, p in dx.iter_paragraphs(root):
        p_ids.append(pid)
        p_elems.append(p)

    prefixes = paragraph_prefixes(p_elems, numbering, styles)
    note_marks, note_refs = nt.paragraph_note_refs(p_elems)

    texts: list[str] = []
    seg_maps: list[list[dx.Segment]] = []
    auto_labels: dict[str, str] = {}
    for i, p in enumerate(p_elems):
        t, segs = dx.paragraph_text_map(
            p, prefix=prefixes[i], note_marks=note_marks[i])
        texts.append(t)
        seg_maps.append(segs)
        if prefixes[i]:
            auto_labels[p_ids[i]] = prefixes[i]

    heading_levels = [
        hd.heading_level(p, t, styles) for p, t in zip(p_elems, texts)
    ]

    # ---- sections -----------------------------------------------------
    sections: list[Section] = []
    para_section: list[str] = []

    def new_section(title: str, canonical: str, heading_pid: str | None) -> Section:
        s = Section(id=f"s{len(sections)}", title=title, canonical=canonical,
                    heading_paragraph_id=heading_pid)
        sections.append(s)
        return s

    cur: Section | None = None  # leading section created lazily
    for i, t in enumerate(texts):
        if heading_levels[i] == 1:
            cur = new_section(t.strip(), hd.canonical_for(t), p_ids[i])
        if cur is None:
            cur = new_section("", "other", None)  # text before the first heading
        para_section.append(cur.id)

    # ---- reference list ----------------------------------------------
    ref_span = _find_ref_span(p_elems, texts, heading_levels)
    ref_para_idx: set[int] = set()
    references: list[Reference] = []
    if ref_span:
        start, end = ref_span
        for i in range(start, end):
            if not texts[i].strip():
                continue
            ref_para_idx.add(i)
            references.append(_list_reference(
                len(references) + 1, p_ids[i], texts[i]))

    # ---- markers ------------------------------------------------------
    detected: list[tuple[int, DetectedMarker]] = []
    managed_by: str | None = None
    for i, p in enumerate(p_elems):
        if i in ref_para_idx:
            continue
        ms, managed = detect_markers(
            p, texts[i], seg_maps[i],
            prefix=prefixes[i], note_marks=note_marks[i])
        if managed and managed_by is None:
            managed_by = managed
        for m in ms:
            detected.append((i, m))

    # footnote/endnote reference marks -> kind="footnote" markers
    for i, ids in enumerate(note_refs):
        if i in ref_para_idx or not ids:
            continue
        note_segs = [s for s in seg_maps[i] if s.virtual == "note"]
        for seg, (nid, kind) in zip(note_segs, ids):
            detected.append((i, DetectedMarker(
                start=seg.start, end=seg.end,
                raw=texts[i][seg.start:seg.end], kind="footnote",
                items=[(nid, kind)])))
    detected.sort(key=lambda t: (t[0], t[1].start))

    # ---- footnote/endnote bodies -> references ------------------------
    note_ref: dict[tuple[str, str], str] = {}
    for i, ids in enumerate(note_refs):
        if i in ref_para_idx:
            continue
        for nid, kind in ids:
            text = note_bodies.get((kind, nid))
            if text is None or not nt.looks_like_reference(text):
                continue
            ref = nt.note_reference(
                f"r{len(references) + 1}", text, p_ids[i])
            references.append(ref)
            note_ref[(kind, nid)] = ref.id

    ref_lists = link_markers([m for _, m in detected], references)
    for k, (_i, m) in enumerate(detected):
        if m.kind == "footnote" and m.items:
            nid, kind = m.items[0]
            rid = note_ref.get((kind, nid))
            ref_lists[k] = [rid] if rid else []

    markers = [
        CitationMarker(
            id=f"m{k}",
            paragraph_id=p_ids[i],
            start=m.start,
            end=m.end,
            raw=m.raw,
            kind=m.kind,
            ref_ids=ref_lists[k],
        )
        for k, (i, m) in enumerate(detected)
    ]

    # ---- document metadata -------------------------------------------
    title = None
    for i, p in enumerate(p_elems):
        sid = dx.paragraph_style_id(p)
        if sid and hd.is_title_style(sid, styles) and texts[i].strip():
            title = texts[i].strip()
            break
    if not title:
        title = core_title
    if not title:
        title = next((t.strip() for t in texts if t.strip()), None)

    styles_seen = {_classify_marker_style(m) for _, m in detected}
    if "numeric" in styles_seen and "author_year" in styles_seen:
        citation_style = "mixed"
    elif "numeric" in styles_seen:
        citation_style = "numeric"
    elif "author_year" in styles_seen:
        citation_style = "author_year"
    else:
        citation_style = "unknown"

    char_offsets: list[int] = []
    cursor = 0
    for t in texts:
        char_offsets.append(cursor)
        cursor += len(t) + 1  # paragraphs joined by "\n"

    word_count = sum(len(re.findall(r"[\w一-鿿]+", t)) for t in texts)

    paragraphs = [
        Paragraph(id=p_ids[i], section_id=para_section[i], text=texts[i],
                  char_offset=char_offsets[i])
        for i in range(len(texts))
    ]

    return ParsedDocument(
        document=Document(
            title=title,
            filename=path.name,
            citation_style=citation_style,  # type: ignore[arg-type]
            managed_by=managed_by,  # type: ignore[arg-type]
            word_count=word_count,
        ),
        sections=sections,
        paragraphs=paragraphs,
        markers=markers,
        references=references,
        auto_labels=auto_labels,
    )


def apply_bibliography_start(parsed: ParsedDocument, start: int) -> int:
    """Treat ``parsed.paragraphs[start:]`` as the bibliography.

    Used only by the LLM-assisted fallback (``bibguess``) after the
    model's claimed boundary has passed deterministic verification.
    Builds list References, drops markers that sit inside the new span,
    and re-links the survivors against the new list. Returns the number
    of references added.
    """
    refs: list[Reference] = list(parsed.references)  # footnote refs keep ids
    ref_pids: set[str] = set()
    n = len(refs)
    for i in range(max(0, start), len(parsed.paragraphs)):
        p = parsed.paragraphs[i]
        if not p.text.strip():
            continue
        ref_pids.add(p.id)
        n += 1
        refs.append(_list_reference(n, p.id, p.text))
    added = n - len(parsed.references)
    if added == 0:
        return 0
    parsed.references = refs
    kept = [m for m in parsed.markers if m.paragraph_id not in ref_pids]
    det = [
        DetectedMarker(start=m.start, end=m.end, raw=m.raw,
                       kind=m.kind or "numeric")
        for m in kept if m.kind != "footnote"
    ]
    lists = link_markers(det, [r for r in refs if r.origin == "list"])
    it = iter(lists)
    for m in kept:
        if m.kind == "footnote":
            continue  # note links stay as they were
        m.ref_ids = next(it)
    parsed.markers = kept
    return added


def relink_markers(parsed: ParsedDocument) -> None:
    """Re-resolve list-reference markers after reference fields changed
    (model re-structuring). Footnote links are positional and kept."""
    det = [
        DetectedMarker(start=m.start, end=m.end, raw=m.raw,
                       kind=m.kind or "numeric")
        for m in parsed.markers if m.kind != "footnote"
    ]
    lists = link_markers(det, [r for r in parsed.references
                               if r.origin == "list"])
    it = iter(lists)
    for m in parsed.markers:
        if m.kind != "footnote":
            m.ref_ids = next(it)
