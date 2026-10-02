"""Footnote/endnote citation support.

Design (documented per T1): every ``w:footnoteReference`` /
``w:endnoteReference`` in the body produces a marker with
``kind="footnote"`` whose ``raw`` is the rendered mark — decimal for
footnotes, lower-roman for endnotes (Word's defaults; numbering styles
in settings.xml are not consulted). The mark is a VIRTUAL segment — it
is not literal text in document.xml — so anchors overlapping only the
mark resolve to no run and comments fall back to whole-paragraph
anchoring (the AGENTS "range too big beats broken formatting" rule).

A note body is promoted to a ``Reference`` (``origin="footnote"``) only
when it parses as a cited source: a (19|20)xx year AND extractable
authors AND >= 25 non-space characters. Commentary notes ("we thank
reviewers") produce markers with empty ref_ids and count toward
nothing downstream. The promoted Reference's ``paragraph_id`` points at
the paragraph holding the reference mark — findings then anchor where
the citation is used — while ``origin="footnote"`` keeps it out of
every positional algorithm (list reorder, numeric position fallback).
"""

from __future__ import annotations

import re
import zipfile

from lxml import etree

from ..refs.structure import parse_reference
from ..schema import Reference
from . import docx_xml as dx
from .numbering import to_roman

W_FOOTNOTE = dx.qn("footnote")
W_ENDNOTE = dx.qn("endnote")
W_ID = dx.qn("id")
W_TYPE = dx.qn("type")

_SEPARATOR_TYPES = {"separator", "continuationSeparator", "continuationNotice"}
_MIN_REF_LEN = 25


def _note_paragraph_text(p: etree._Element) -> str:
    """Visible text of one footnote/endnote body paragraph (the
    w:footnoteRef/w:endnoteRef mark element is not a text tag and is
    simply ignored)."""
    text, _ = dx.paragraph_text_map(p)
    return text


def load_note_bodies(
    zf: zipfile.ZipFile,
) -> dict[tuple[str, str], str]:
    """(kind, note_id) -> text for real notes in footnotes.xml and
    endnotes.xml. Separator/continuation notes are skipped. The key
    carries the kind because the two parts number independently."""
    out: dict[tuple[str, str], str] = {}
    for part, tag, kind in (
        ("word/footnotes.xml", W_FOOTNOTE, "footnote"),
        ("word/endnotes.xml", W_ENDNOTE, "endnote"),
    ):
        try:
            root = etree.fromstring(zf.read(part))
        except KeyError:
            continue
        for note in root.iter(tag):
            nid = note.get(W_ID)
            if nid is None or note.get(W_TYPE) in _SEPARATOR_TYPES:
                continue
            text = " ".join(
                t for t in (_note_paragraph_text(p).strip()
                            for p in note.iter(dx.W_P)) if t
            )
            out[(kind, nid)] = text
    return out


def paragraph_note_refs(
    p_elems: list[etree._Element],
) -> tuple[list[list[str]], list[list[tuple[str, str]]]]:
    """Walk body paragraphs in order; per paragraph return the ordered
    (mark_texts, [(note_id, kind)]) of footnote/endnote references.

    Marks are numbered per kind by document order of the reference
    marks — the same scheme Word's continuous decimal (footnotes) and
    lower-roman (endnotes) defaults render.
    """
    marks: list[list[str]] = []
    ids: list[list[tuple[str, str]]] = []
    fn_n = 0
    en_n = 0
    for p in p_elems:
        pm: list[str] = []
        pi: list[tuple[str, str]] = []
        for el, _run in dx._iter_nodes(p):
            nid = el.get(W_ID)
            if el.tag == dx.W_FOOTNOTEREF and nid is not None:
                fn_n += 1
                pm.append(str(fn_n))
                pi.append((nid, "footnote"))
            elif el.tag == dx.W_ENDNOTEREF and nid is not None:
                en_n += 1
                pm.append(to_roman(en_n))
                pi.append((nid, "endnote"))
        marks.append(pm)
        ids.append(pi)
    return marks, ids


def looks_like_reference(text: str) -> bool:
    """Is this note body a cited source (not commentary)?"""
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) < _MIN_REF_LEN:
        return False
    info = parse_reference(t)
    return info["year"] is not None and bool(info["authors"])


def note_reference(
    rid: str, text: str, citing_paragraph_id: str
) -> Reference:
    """Promote a note body to a Reference anchored at its citing
    paragraph. ``label`` stays None: note marks render their own numbers
    and must never be reached by numeric position resolution."""
    info = parse_reference(text)
    return Reference(
        id=rid,
        raw=text.strip(),
        title=info["title"],
        authors=info["authors"],
        year=info["year"],
        venue=info["venue"],
        doi=info["doi"],
        lang=info["lang"],
        paragraph_id=citing_paragraph_id,
        label=None,
        origin="footnote",
    )
