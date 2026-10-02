"""Resolve Word auto-numbering (w:numPr -> word/numbering.xml) into the
literal labels Word renders, e.g. "[1] ", "1. ", "3.2 ".

Why: students upload docx files where reference entries and section
headings carry their numbers from list numbering, not from literal text.
Without this, an auto-numbered bibliography is invisible to the
reference-list tail detector and numbered markers cannot link to it.

Supported paths (the common Word/WPS outputs):
- paragraph-level ``w:pPr/w:numPr`` (numId + optional ilvl, numId=0 or
  missing numId disables/falls back);
- numbering inherited through the paragraph style chain (styles whose
  pPr carries numPr), following basedOn;
- ``w:num`` -> ``w:abstractNum`` -> ``w:lvl`` with ``w:start``,
  ``w:numFmt``, ``w:lvlText`` ("%1".."％9" placeholders), ``w:suff`` and
  ``w:num/w:lvlOverride/w:startOverride``.

Not implemented (documented limits): ``w:lvl`` pStyle linkage (levels
that apply to a style without any numPr), picture bullets, and
``w:numPicBullet``. Counters are per-numId; a level increment resets all
deeper levels, matching Word's restart behaviour for the common shapes.

Formats: decimal, decimalZero, upper/lowerLetter, upper/lowerRoman,
chineseCounting* (approximated as decimal), bullet (literal lvlText
character), none (no label).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from . import docx_xml as dx
from .headings import StyleInfo

W_LVL = dx.qn("lvl")
W_ILVL_ATTR = dx.qn("ilvl")
W_START = dx.qn("start")
W_NUMFMT = dx.qn("numFmt")
W_LVLTEXT = dx.qn("lvlText")
W_SUFF = dx.qn("suff")
W_ABSTRACTNUM = dx.qn("abstractNum")
W_NUM = dx.qn("num")
W_ABSTRACTNUMID = dx.qn("abstractNumId")
W_LVLOVERRIDE = dx.qn("lvlOverride")
W_STARTOVERRIDE = dx.qn("startOverride")
W_NUMPR = dx.W_NUMPR
W_NUMID = dx.W_NUMID
W_ILVL = dx.W_ILVL

_PLACEHOLDER = re.compile(r"%([1-9])")


def to_roman(n: int) -> str:
    """1 -> 'i' (lowercase). Out-of-range/0 falls back to str(n)."""
    if n <= 0 or n >= 4000:
        return str(n)
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
            (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
            (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def _to_letters(n: int) -> str:
    """1 -> 'a', 27 -> 'aa' (Excel-style)."""
    if n <= 0:
        return str(n)
    out = []
    while n > 0:
        n, r = divmod(n - 1, 26)
        out.append(chr(ord("a") + r))
    return "".join(reversed(out))


def format_counter(n: int, fmt: str) -> str:
    if fmt == "decimalZero":
        return f"{n:02d}"
    if fmt == "upperLetter":
        return _to_letters(n).upper()
    if fmt == "lowerLetter":
        return _to_letters(n)
    if fmt == "upperRoman":
        return to_roman(n).upper()
    if fmt == "lowerRoman":
        return to_roman(n)
    # decimal + chineseCounting* + unknown formats
    return str(n)


@dataclass
class Lvl:
    num_fmt: str = "decimal"
    lvl_text: str = "%1."
    start: int = 1
    suffix: str = "tab"  # tab | space | nothing


@dataclass
class Numbering:
    # numId -> ilvl -> Lvl (startOverride already folded in)
    lvls: dict[int, dict[int, Lvl]] = field(default_factory=dict)

    def lvl(self, num_id: int, ilvl: int) -> Lvl | None:
        per = self.lvls.get(num_id)
        if per is None:
            return None
        return per.get(ilvl) or per.get(0)


def _wval(el: etree._Element | None, default: str = "") -> str:
    if el is None:
        return default
    return el.get(dx.W_VAL) or default


def load_numbering(root: etree._Element | None) -> Numbering | None:
    """Parse word/numbering.xml into a Numbering, or None."""
    if root is None:
        return None
    abstracts: dict[str, dict[int, Lvl]] = {}
    for an in root.iter(W_ABSTRACTNUM):
        aid = an.get(dx.qn("abstractNumId"))
        if aid is None:
            continue
        lvls: dict[int, Lvl] = {}
        for lv in an.findall(W_LVL):
            try:
                ilvl = int(lv.get(W_ILVL_ATTR, "0"))
            except ValueError:
                ilvl = 0
            try:
                start = int(_wval(lv.find(W_START), "1"))
            except ValueError:
                start = 1
            lvls[ilvl] = Lvl(
                num_fmt=_wval(lv.find(W_NUMFMT), "decimal"),
                lvl_text=_wval(lv.find(W_LVLTEXT), f"%{ilvl + 1}."),
                start=start,
                suffix=_wval(lv.find(W_SUFF), "tab"),
            )
        abstracts[aid] = lvls

    out = Numbering()
    for num in root.iter(W_NUM):
        try:
            num_id = int(num.get(dx.qn("numId"), ""))
        except ValueError:
            continue
        aid_el = num.find(W_ABSTRACTNUMID)
        aid = _wval(aid_el)
        lvls = {k: Lvl(v.num_fmt, v.lvl_text, v.start, v.suffix)
                for k, v in abstracts.get(aid, {}).items()}
        for ov in num.findall(W_LVLOVERRIDE):
            try:
                ilvl = int(ov.get(W_ILVL_ATTR, "0"))
            except ValueError:
                continue
            so = ov.find(W_STARTOVERRIDE)
            if so is not None and ilvl in lvls:
                try:
                    lvls[ilvl].start = int(_wval(so, "1"))
                except ValueError:
                    pass
            # a lvlOverride with a full w:lvl child replaces the level
            lv_el = ov.find(W_LVL)
            if lv_el is not None:
                try:
                    start = int(_wval(lv_el.find(W_START), "1"))
                except ValueError:
                    start = 1
                lvls[ilvl] = Lvl(
                    num_fmt=_wval(lv_el.find(W_NUMFMT), "decimal"),
                    lvl_text=_wval(lv_el.find(W_LVLTEXT), f"%{ilvl + 1}."),
                    start=start,
                    suffix=_wval(lv_el.find(W_SUFF), "tab"),
                )
        out.lvls[num_id] = lvls
    return out if out.lvls else None


def _para_numpr(p: etree._Element) -> tuple[int | None, int] | None:
    """The paragraph's own numPr -> (numId, ilvl); numId None = inherit."""
    ppr = p.find(dx.W_PPR)
    if ppr is None:
        return None
    numpr = ppr.find(W_NUMPR)
    if numpr is None:
        return None
    num_id: int | None = None
    nid = numpr.find(W_NUMID)
    if nid is not None:
        try:
            num_id = int(_wval(nid, "0"))
        except ValueError:
            num_id = 0
    ilvl = 0
    ilv = numpr.find(W_ILVL)
    if ilv is not None:
        try:
            ilvl = int(_wval(ilv, "0"))
        except ValueError:
            ilvl = 0
    return num_id, ilvl


def _style_numpr(
    sid: str | None, styles: dict[str, StyleInfo]
) -> tuple[int, int] | None:
    """numPr inherited through the paragraph style's basedOn chain."""
    seen: set[str] = set()
    cur = sid
    while cur and cur not in seen and cur in styles:
        seen.add(cur)
        info = styles[cur]
        if info.num_id is not None:
            if info.num_id == 0:
                return None
            return info.num_id, info.ilvl or 0
        cur = info.based_on
    return None


def effective_numpr(
    p: etree._Element, styles: dict[str, StyleInfo]
) -> tuple[int, int] | None:
    """(numId, ilvl) for a paragraph, or None when it is not numbered.

    Paragraph-level numPr wins; numId=0 (or missing numId) disables —
    otherwise the value comes from the style chain.
    """
    own = _para_numpr(p)
    if own is not None:
        num_id, ilvl = own
        if num_id == 0:
            return None
        if num_id is not None:
            return num_id, ilvl
        # numId missing from numPr -> fall through to the style's numId
        style_npr = _style_numpr(dx.paragraph_style_id(p), styles)
        if style_npr is None:
            return None
        return style_npr[0], ilvl
    return _style_numpr(dx.paragraph_style_id(p), styles)


def _expand(lvl_text: str, counters: dict[int, int],
            lvls: dict[int, Lvl]) -> str:
    """Fill %1..%9 in lvlText with current counters (start values for
    levels not yet used)."""
    def sub(m: re.Match) -> str:
        ilvl = int(m.group(1)) - 1
        if ilvl in counters:
            n = counters[ilvl]
        else:
            n = lvls.get(ilvl, Lvl()).start
        fmt = lvls.get(ilvl, Lvl()).num_fmt
        return format_counter(n, fmt)

    return _PLACEHOLDER.sub(sub, lvl_text)


def paragraph_prefixes(
    p_elems: list[etree._Element],
    numbering: Numbering | None,
    styles: dict[str, StyleInfo],
) -> list[str]:
    """Rendered label ("[1] ", "1. ") per paragraph, "" when none.

    The returned list is parallel to ``p_elems``. Labels end with a
    space when the level's suffix is tab or space; "nothing" keeps the
    label glued to the text.
    """
    if numbering is None:
        return [""] * len(p_elems)
    counters: dict[int, dict[int, int]] = {}
    out: list[str] = []
    for p in p_elems:
        npr = effective_numpr(p, styles)
        if npr is None:
            out.append("")
            continue
        num_id, ilvl = npr
        per = numbering.lvls.get(num_id)
        lvl = numbering.lvl(num_id, ilvl)
        if per is None or lvl is None or lvl.num_fmt == "none":
            out.append("")
            continue
        ctrs = counters.setdefault(num_id, {})
        ctrs[ilvl] = ctrs.get(ilvl, lvl.start - 1) + 1
        for deeper in [k for k in ctrs if k > ilvl]:
            del ctrs[deeper]
        label = _expand(lvl.lvl_text, ctrs, per)
        if not label:
            out.append("")
            continue
        sep = "" if lvl.suffix == "nothing" else " "
        out.append(label + sep)
    return out
