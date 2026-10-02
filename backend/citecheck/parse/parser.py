"""Orchestrates docx parsing: paragraphs -> sections -> reference list ->
markers -> linking -> Document metadata.

Public entry: ``parse_docx(path) -> ParsedDocument``. The input file is
opened read-only and never modified.
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
from .links import link_markers
from .markers import DetectedMarker, detect_markers

_ZIP_DOC = "word/document.xml"
_ZIP_STYLES = "word/styles.xml"
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
    # last resort: a trailing run of numbered-entry paragraphs
    tail = len(texts)
    while tail > 0 and _CITE_LABEL_RE.match(texts[tail - 1].strip()):
        tail -= 1
    if len(texts) - tail >= 3:
        return tail, len(texts)
    return None


def _classify_marker_style(m: DetectedMarker) -> str:
    if m.kind in {"numeric", "superscript"}:
        return "numeric"
    if m.kind == "author_year":
        return "author_year"
    # field-managed: judge by the visible result text
    if re.match(r"^\s*[\[\(【（［]?\d", m.raw):
        return "numeric"
    return "author_year"


def parse_docx(path: str | Path) -> ParsedDocument:
    path = Path(path)
    with zipfile.ZipFile(path) as zf:
        root = _read_part(zf, _ZIP_DOC)
        if root is None:
            raise ValueError(f"{path.name}: word/document.xml not found")
        styles = hd.load_styles(_read_part(zf, _ZIP_STYLES))
        core_title = _core_title(zf)

    p_elems: list[etree._Element] = []
    p_ids: list[str] = []
    texts: list[str] = []
    seg_maps: list[list[dx.Segment]] = []
    for pid, p in dx.iter_paragraphs(root):
        t, segs = dx.paragraph_text_map(p)
        p_ids.append(pid)
        p_elems.append(p)
        texts.append(t)
        seg_maps.append(segs)

    heading_levels = [
        hd.heading_level(p, t, styles) for p, t in zip(p_elems, texts)
    ]

    # ---- sections -----------------------------------------------------
    sections: list[Section] = []
    para_section: list[str] = []

    def new_section(title: str, canonical: str) -> Section:
        s = Section(id=f"s{len(sections)}", title=title, canonical=canonical)
        sections.append(s)
        return s

    cur: Section | None = None  # leading section created lazily
    for i, t in enumerate(texts):
        if heading_levels[i] == 1:
            cur = new_section(t.strip(), hd.canonical_for(t))
        if cur is None:
            cur = new_section("", "other")  # text before the first heading
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
            info = parse_reference(texts[i])
            references.append(
                Reference(
                    id=f"r{len(references) + 1}",
                    raw=texts[i].strip(),
                    title=info["title"],
                    authors=info["authors"],
                    year=info["year"],
                    venue=info["venue"],
                    doi=info["doi"],
                    lang=info["lang"],
                    paragraph_id=p_ids[i],
                    label=info["label"],
                )
            )

    # ---- markers ------------------------------------------------------
    detected: list[tuple[int, DetectedMarker]] = []
    managed_by: str | None = None
    for i, p in enumerate(p_elems):
        if i in ref_para_idx:
            continue
        ms, managed = detect_markers(p, texts[i], seg_maps[i])
        if managed and managed_by is None:
            managed_by = managed
        for m in ms:
            detected.append((i, m))

    ref_lists = link_markers([m for _, m in detected], references)
    markers = [
        CitationMarker(
            id=f"m{k}",
            paragraph_id=p_ids[i],
            start=m.start,
            end=m.end,
            raw=m.raw,
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
    )
