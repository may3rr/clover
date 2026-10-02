"""Heading detection and section canonicalisation.

Headings are found two ways, style first then regex fallback:
1. Paragraph style: resolve the pStyle styleId through word/styles.xml.
   Localised Word files use styleIds like "1"/"2" whose w:name is
   "heading 1"/"标题 1"; an explicit w:outlineLvl on the paragraph or
   anywhere in the style's basedOn chain also marks a heading.
2. Numbered-heading regex on short paragraphs ("1 引言", "2. Related
   Work", "3.1 Architecture", "一、引言") when no style applies.

Each heading's canonical bucket comes from CANONICAL_KEYWORDS, an
extensible zh/en keyword dict — extend it, don't branch on literal titles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from . import docx_xml as dx

# Order matters: the first bucket whose keyword matches wins.
CANONICAL_KEYWORDS: dict[str, list[str]] = {
    "intro": ["introduction", "引言", "绪论", "简介"],
    "related": [
        "related work",
        "literature review",
        "prior work",
        "background",
        "相关工作",
        "研究现状",
        "文献综述",
        "研究背景",
    ],
    "method": [
        "methodology",
        "method",
        "approach",
        "model",
        "system",
        "design",
        "方法",
        "模型",
        "方法概述",
        "系统设计",
    ],
    "experiment": [
        "experiment",
        "evaluation",
        "result",
        "empirical",
        "setup",
        "实验",
        "评测",
        "评估",
        "结果",
    ],
    "discussion": ["discussion", "analysis", "讨论", "分析"],
    "conclusion": [
        "conclusion",
        "summary",
        "concluding",
        "future work",
        "结论",
        "总结",
        "结语",
        "展望",
    ],
}

REF_HEADING_RE = re.compile(
    r"^(references|bibliography|works?\s+cited|literature\s+cited|"
    r"参考文献|引用文献|文献)$",
    re.IGNORECASE,
)

_NUMBERED_HEADING_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)*)\s*[\.、]?[\s　]*(\S.*)$"
)
_ZH_NUMBERED_HEADING_RE = re.compile(r"^\s*[一二三四五六七八九十百]+[、．.]\s*\S")
_YEAR_PROSE_RE = re.compile(r"^\s*(19|20)\d{2}\s*年")

_MAX_HEADING_LEN = 60


@dataclass
class StyleInfo:
    name: str
    outline_lvl: int | None
    based_on: str | None
    num_id: int | None = None
    ilvl: int | None = None


def load_styles(styles_root: etree._Element | None) -> dict[str, StyleInfo]:
    """styleId -> StyleInfo from word/styles.xml."""
    styles: dict[str, StyleInfo] = {}
    if styles_root is None:
        return styles
    for st in styles_root.iter(dx.qn("style")):
        sid = st.get(dx.qn("styleId"))
        if not sid:
            continue
        name_el = st.find(dx.qn("name"))
        ppr = st.find(dx.qn("pPr"))
        ol_el = ppr.find(dx.qn("outlineLvl")) if ppr is not None else None
        bo_el = st.find(dx.qn("basedOn"))
        try:
            ol = int(ol_el.get(dx.W_VAL)) if ol_el is not None else None
        except ValueError:
            ol = None
        num_id = ilvl = None
        numpr = ppr.find(dx.W_NUMPR) if ppr is not None else None
        if numpr is not None:
            nid = numpr.find(dx.W_NUMID)
            if nid is not None:
                try:
                    num_id = int(nid.get(dx.W_VAL) or "0")
                except ValueError:
                    num_id = 0
            ilv = numpr.find(dx.W_ILVL)
            if ilv is not None:
                try:
                    ilvl = int(ilv.get(dx.W_VAL) or "0")
                except ValueError:
                    ilvl = 0
        styles[sid] = StyleInfo(
            name=(name_el.get(dx.W_VAL) or "") if name_el is not None else "",
            outline_lvl=ol,
            based_on=bo_el.get(dx.W_VAL) if bo_el is not None else None,
            num_id=num_id,
            ilvl=ilvl,
        )
    return styles


def style_heading_level(sid: str, styles: dict[str, StyleInfo]) -> int | None:
    """1-based heading level for a styleId, following basedOn chains.

    Recognises names like 'heading 2' / '标题 2' and an explicit
    outlineLvl (0 = level 1) on the style or its ancestors.
    """
    seen: set[str] = set()
    cur = sid
    while cur and cur not in seen and cur in styles:
        seen.add(cur)
        info = styles[cur]
        m = re.match(r"^(?:heading|标题)\s*(\d+)", info.name.strip().lower())
        if m:
            return int(m.group(1))
        if info.outline_lvl is not None and info.outline_lvl <= 8:
            return info.outline_lvl + 1
        cur = info.based_on
    return None


def is_title_style(sid: str, styles: dict[str, StyleInfo]) -> bool:
    info = styles.get(sid)
    if info is None:
        return False
    return info.name.strip().lower() in {"title", "标题"}


def heading_level(
    p: etree._Element, text: str, styles: dict[str, StyleInfo]
) -> int | None:
    """Heading level (1-based) of a paragraph, or None if body text."""
    sid = dx.paragraph_style_id(p)
    if sid:
        lvl = style_heading_level(sid, styles)
        if lvl is not None:
            return lvl
    ol = dx.paragraph_outline_lvl(p)
    if ol is not None and ol <= 8:
        return ol + 1

    stripped = text.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LEN:
        return None
    if _YEAR_PROSE_RE.match(stripped):
        return None
    m = _NUMBERED_HEADING_RE.match(stripped)
    if m and m.group(1).count(".") <= 4 and len(m.group(2)) >= 1:
        # avoid "3.14 is the value of pi"-style prose: heading titles do not
        # end with a sentence terminator
        if not re.search(r"[。．.!！?？]$", stripped):
            return m.group(1).count(".") + 1
    if _ZH_NUMBERED_HEADING_RE.match(stripped):
        return 1
    return None


def canonical_for(title: str) -> str:
    """Map a section title to intro|related|method|experiment|
    discussion|conclusion|other via CANONICAL_KEYWORDS."""
    t = re.sub(r"^\s*[\d一二三四五六七八九十百\.、．\s]*", "", title).strip().lower()
    for canonical, keywords in CANONICAL_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in t:
                return canonical
    return "other"


def is_ref_heading(text: str) -> bool:
    """True for '参考文献' / 'References' / 'Bibliography' / 'Works Cited'
    headings (with optional numbering stripped first)."""
    t = re.sub(r"^\s*[\d一二三四五六七八九十百\.、．\s]*", "", text).strip()
    return bool(REF_HEADING_RE.match(t))
