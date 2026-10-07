"""Tables, figures and captions in a docx, for the reading view.

``iter_paragraphs`` already yields table-cell paragraphs in document
order; this module only adds where each one sits (table, row, column)
and which embedded images a paragraph carries. Text, anchors and checks
are unaffected.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import PurePosixPath

from lxml import etree

from ..schema import TableCell
from . import docx_xml as dx
from .assets import Bundle
from .headings import StyleInfo

W_TBL = dx.qn("tbl")
W_TR = dx.qn("tr")
W_TC = dx.qn("tc")
W_TCPR = dx.qn("tcPr")
W_GRIDSPAN = dx.qn("gridSpan")
W_TRPR = dx.qn("trPr")
W_TBLHEADER = dx.qn("tblHeader")
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_V_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_RELS = "word/_rels/document.xml.rels"
# "Figure 2: ..." / "Table 3. ..." — the punctuation keeps body sentences
# such as "Table 3 shows ..." out
_CAPTION_TEXT = re.compile(
    r"^\s*(Figure|Fig\.|Table|Tab\.)\s*[0-9]+(?:\.[0-9]+)*\s*[.:：|](?:\s|$)")


def _span(tc: etree._Element) -> int:
    pr = tc.find(W_TCPR)
    gs = pr.find(W_GRIDSPAN) if pr is not None else None
    try:
        return max(int(gs.get(dx.W_VAL, "1")), 1) if gs is not None else 1
    except ValueError:
        return 1


def table_cells(root: etree._Element,
                p_elems: list[etree._Element]) -> list[TableCell | None]:
    """Innermost table cell of every paragraph (None outside tables)."""
    # keyed by the element itself: lxml proxies are recreated on access,
    # so id() of one is not stable
    table_ids = {t: f"t{k}" for k, t in enumerate(root.iter(W_TBL))}
    out: list[TableCell | None] = []
    cache: dict[etree._Element, TableCell] = {}
    for p in p_elems:
        tc = next((a for a in p.iterancestors(W_TC)), None)
        if tc is None:
            out.append(None)
            continue
        hit = cache.get(tc)
        if hit is None:
            tr = tc.getparent()
            tbl = tr.getparent() if tr is not None else None
            if tr is None or tbl is None or tr.tag != W_TR:
                out.append(None)
                continue
            rows = [r for r in tbl if r.tag == W_TR]
            row = rows.index(tr)
            col = 0
            for c in tr:
                if c is tc:
                    break
                if c.tag == W_TC:
                    col += _span(c)
            trpr = tr.find(W_TRPR)
            header = row == 0 or (
                trpr is not None and trpr.find(W_TBLHEADER) is not None)
            hit = TableCell(table=table_ids.get(tbl, "t?"), row=row,
                            col=col, colspan=_span(tc), header=header)
            cache[tc] = hit
        out.append(hit)
    return out


def _image_rels(zf: zipfile.ZipFile) -> dict[str, str]:
    try:
        root = etree.fromstring(zf.read(_RELS))
    except (KeyError, etree.XMLSyntaxError):
        return {}
    rels: dict[str, str] = {}
    for r in root.iter(_PKG_REL):
        if r.get("Type", "").endswith("/image") and r.get("TargetMode") != "External":
            target = PurePosixPath("word") / r.get("Target", "")
            # normalise "word/../media/x.png" style targets
            parts: list[str] = []
            for part in target.parts:
                if part == "..":
                    if parts:
                        parts.pop()
                elif part != ".":
                    parts.append(part)
            rels[r.get("Id", "")] = "/".join(parts)
    return rels


def paragraph_images(zf: zipfile.ZipFile, p_elems: list[etree._Element],
                     bundle: Bundle) -> list[list[str]]:
    """Asset names of the images embedded in each paragraph."""
    rels = _image_rels(zf)
    names = set(zf.namelist())
    stored: dict[str, str | None] = {}
    out: list[list[str]] = []
    for p in p_elems:
        found: list[str] = []
        for el in p.iter(_A_BLIP, _V_IMAGEDATA):
            rid = el.get(f"{{{_R_NS}}}embed") or el.get(f"{{{_R_NS}}}id")
            target = rels.get(rid or "")
            if not target or target not in names:
                continue
            if target not in stored:
                pp = PurePosixPath(target)
                stored[target] = bundle.add_bytes(
                    zf.read(target), pp.stem, pp.suffix)
            name = stored[target]
            if name and name not in found:
                found.append(name)
        out.append(found)
    return out


def is_caption(p: etree._Element, text: str,
               styles: dict[str, StyleInfo]) -> bool:
    sid = dx.paragraph_style_id(p)
    if sid:
        info = styles.get(sid)
        name = (info.name if info else sid).strip().lower()
        if name in {"caption", "题注"} or sid.lower() == "caption":
            return True
    return bool(_CAPTION_TEXT.match(text)) and len(text) < 800
