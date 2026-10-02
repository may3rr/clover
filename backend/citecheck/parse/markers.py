"""Citation-marker detection inside a paragraph, by priority:

1. Zotero / EndNote field codes (complex fldChar fields and fldSimple) —
   the structured instruction data is the most accurate source.
2. Superscript runs containing citation numbers ("1", "1,3", "2–5", "[4]").
3. Regexes over the remaining text: [1] / [1,3] / [2-5] and author-year
   forms ((Smith, 2020), (Smith et al., 2020; Lee, 2021),
   (Smith & Lee, 2020a), Smith et al. (2020), 张三等(2020), （张三，2020）,
   张三和李四（2020）).

Lower-priority detectors skip spans already covered by a higher-priority
marker. Marker detection is never run on reference-list paragraphs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from lxml import etree

from . import docx_xml as dx

MarkerKind = Literal["zotero", "endnote", "superscript", "numeric", "author_year"]

SUPERSCRIPT_RE = re.compile(
    r"^\s*[\[\(【（［]?\d[\d,，、;；\-–—~～\s]*[\]\)】）］]?\s*$"
)

_NUMERIC_RE = re.compile(
    r"[\[【［]\s*\d+(?:\s*[-–—~～]\s*\d+)?"
    r"(?:\s*[,，、;；]\s*\d+(?:\s*[-–—~～]\s*\d+)?)*\s*[\]】］]"
)

_EN_SURNAME = (
    r"(?:(?:van|von|de|der|den|di|la|le)\s+)?"
    r"[A-Z][A-Za-z'’\-]+"
    r"(?:\s+(?:van|von|de|der|den|di|la|le)\s+[A-Z][A-Za-z'’\-]+)*"
)
_EN_AUTHORS = (
    _EN_SURNAME
    + r"(?:\s+(?:et\s+al\.?|and\s+" + _EN_SURNAME + r"|&\s*" + _EN_SURNAME + r"))?"
)
_ZH_NAME = r"[一-鿿]{2,4}"
_ZH_AUTHORS = _ZH_NAME + r"(?:(?:等)|(?:和" + _ZH_NAME + r"))?"
_YEAR = r"(?:19|20)\d{2}[a-z]?"
_AUTHORS = f"(?:{_EN_AUTHORS}|{_ZH_AUTHORS})"

_PAREN_ITEM = _AUTHORS + r"\s*[,，]?\s*" + _YEAR
_PAREN_RE = re.compile(
    r"[\(（]\s*" + _PAREN_ITEM + r"(?:\s*[;；]\s*" + _PAREN_ITEM + r")*\s*[\)）]"
)
_NARRATIVE_RE = re.compile(
    _AUTHORS + r"\s*[\(（]\s*" + _YEAR + r"\s*[\)）]"
)


@dataclass
class DetectedMarker:
    start: int
    end: int
    raw: str
    kind: MarkerKind
    items: list = field(default_factory=list)


def _extract_json(instr: str) -> dict | None:
    idx = instr.find("{")
    if idx < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(instr[idx:])
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _field_markers(
    p: etree._Element, segments: list[dx.Segment]
) -> tuple[list[DetectedMarker], str | None]:
    out: list[DetectedMarker] = []
    managed: str | None = None
    fields = dx.paragraph_fields(p) + dx.fldsimple_fields(p, segments)
    for f in fields:
        if f.span is None:
            continue
        kind: MarkerKind | None = None
        items: list = []
        if "ZOTERO_ITEM" in f.instr:
            kind, managed = "zotero", "zotero"
            data = _extract_json(f.instr)
            if data:
                for it in data.get("citationItems", []):
                    if isinstance(it, dict) and it.get("itemData"):
                        items.append(it["itemData"])
        elif "EN.CITE" in f.instr or "ADDIN EN." in f.instr:
            kind, managed = "endnote", "endnote"
        if kind is not None:
            out.append(
                DetectedMarker(start=f.span[0], end=f.span[1], raw="", kind=kind, items=items)
            )
    return out, managed


def _superscript_markers(
    segments: list[dx.Segment], covered: list[bool]
) -> list[DetectedMarker]:
    out: list[DetectedMarker] = []
    cluster: list[dx.Segment] = []

    def flush() -> None:
        if not cluster:
            return
        raw = "".join(s.text for s in cluster)
        span_covered = any(covered[cluster[0].start : cluster[-1].end])
        if not span_covered and SUPERSCRIPT_RE.match(raw) and any(c.isdigit() for c in raw):
            out.append(
                DetectedMarker(
                    start=cluster[0].start, end=cluster[-1].end, raw="", kind="superscript"
                )
            )
        cluster.clear()

    for seg in segments:
        if dx.is_superscript_run(seg.run) and seg.text.strip():
            if cluster and seg.start != cluster[-1].end:
                flush()
            cluster.append(seg)
        else:
            flush()
    flush()
    return out


def _regex_markers(
    text: str, covered: list[bool]
) -> list[DetectedMarker]:
    found: list[DetectedMarker] = []

    def free(m: re.Match) -> bool:
        return not any(covered[m.start() : m.end()])

    for m in _NUMERIC_RE.finditer(text):
        if free(m):
            found.append(DetectedMarker(m.start(), m.end(), "", "numeric"))
    for m in _PAREN_RE.finditer(text):
        if free(m):
            found.append(DetectedMarker(m.start(), m.end(), "", "author_year"))
    for m in _NARRATIVE_RE.finditer(text):
        if free(m):
            found.append(DetectedMarker(m.start(), m.end(), "", "author_year"))
    found.sort(key=lambda d: d.start)
    return found


def detect_markers(
    p: etree._Element, text: str, segments: list[dx.Segment]
) -> tuple[list[DetectedMarker], str | None]:
    """Detect citation markers in one paragraph.

    Returns ``(markers, managed_by)`` where managed_by is "zotero"/"endnote"
    if a field-code marker was seen. Markers carry absolute offsets into
    ``text``; ``raw`` is filled with the visible text span.
    """
    managed: str | None = None
    detected, managed = _field_markers(p, segments)

    covered = [False] * len(text)

    def cover(d: DetectedMarker) -> None:
        for i in range(d.start, min(d.end, len(text))):
            covered[i] = True

    for d in detected:
        cover(d)

    sup = _superscript_markers(segments, covered)
    for d in sup:
        cover(d)
    detected += sup

    detected += _regex_markers(text, covered)

    detected.sort(key=lambda d: d.start)
    for d in detected:
        d.raw = text[d.start : d.end]
    return detected, managed
