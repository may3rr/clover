"""哪些 PDF 是目标期刊的范文：刊名识别、刊名匹配、论文类型。

A PDF's journal, most trusted first:
1. the CNKI cover or 「引用本文」 entry (scan.py already read it);
2. the registry's traces of a journal (DOI prefix, ISSN, CN number) on
   the paper's own first page, or its DOI;
3. a journal named in the running header / footer of the first pages;
4. when none of these answer and the model is allowed: the first page's
   opening and closing lines, asked once (a multiple-choice-free short
   answer, cached like every model call).

A PDF matches the target journal when its journal is the same name, an
alias in the registry, or the target's name stands in its header. The
user sees every candidate on the confirmation page and has the last
word; this module only proposes.
"""

from __future__ import annotations

import asyncio
import logging
import re

from pydantic import BaseModel
from rapidfuzz import fuzz

from .scan import LocalPdf
from .text import squash

log = logging.getLogger(__name__)

_REVIEW_RE = re.compile(
    r"综述|研究进展|研究现状|述评|评述|回顾与展望|发展现状|"
    r"\bsurvey\b|\breview\b|\boverview\b", re.I)
_HEAD_CHARS = 300  # running header / first lines of a page
_FOOT_CHARS = 240


def paper_type(title: str | None) -> str:
    """review | research, from the title (综述 / 研究进展 / survey …)."""
    return "review" if title and _REVIEW_RE.search(title) else "research"


def clean_venue(name: str | None) -> str:
    return re.sub(r"^[《〈]|[》〉]$", "", (name or "").strip()).strip()


def _registry():
    from ..distribution.registry import find_venue, load_venues

    return find_venue, load_venues


def same_venue(a: str | None, b: str | None) -> bool:
    """Two journal names denote the same journal: equal after squashing,
    aliases of one registry entry, or a near-identical spelling."""
    a, b = clean_venue(a), clean_venue(b)
    if not a or not b:
        return False
    ka, kb = squash(a), squash(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    find_venue, _ = _registry()
    va, vb = find_venue(a), find_venue(b)
    if va is not None and va is vb:
        return True
    return min(len(ka), len(kb)) >= 6 and fuzz.ratio(ka, kb) >= 92


_REFS_CUT = re.compile(r"参考文献|References\b|Bibliography", re.I)


def _edges(pdf: LocalPdf) -> str:
    """Running header and footer of page one, running header of page two;
    never the reference list, where cited journals are named."""
    pages = pdf.pages[pdf.cover_pages:pdf.cover_pages + 2]
    out = []
    for k, p in enumerate(pages):
        m = _REFS_CUT.search(p)
        p = p[:m.start()] if m else p
        out.append(p[:_HEAD_CHARS if k == 0 else 150])
        if k == 0:
            out.append(p[-_FOOT_CHARS:])
    return "\n".join(out)


def _names(venue: str, entry: dict | None) -> list[str]:
    names = [clean_venue(venue)]
    if entry:
        names += [entry["name"], *entry.get("aliases", [])]
    # short names ("ACL") would match too much running text
    return [n for n in dict.fromkeys(names) if len(squash(n)) >= 4]


def venue_from_traces(pdf: LocalPdf) -> tuple[str | None, str | None]:
    """(journal, how) from registry traces on the paper's own first page."""
    _, load_venues = _registry()
    head = " ".join(pdf.pages[:pdf.cover_pages + 1])[:3000]
    for v in load_venues():
        for d in v.get("detect", []):
            if d.startswith("10.") and pdf.doc.doi and pdf.doc.doi.lower().startswith(d.lower()):
                return v["name"], "doi_prefix"
        for d in v.get("detect", []):
            if d.lower() in head.lower():
                return v["name"], "doi_prefix" if d.startswith("10.") else "issn"
    return None, None


def header_names(pdf: LocalPdf, venue: str, entry: dict | None) -> bool:
    edges = squash(_edges(pdf))
    return any(squash(n) in edges for n in _names(venue, entry))


class _Venue(BaseModel):
    venue: str | None = None


_PROMPT = (
    "下面是一篇论文 PDF 第一页的开头和结尾文字。判断这篇论文发表在哪个期刊或会议。"
    "只有页面文字里明确写出刊名或会议名时才回答，写出的名称照抄原文；看不出来就填 null，不要猜。"
    "只输出 JSON：{{\"venue\": 刊名或 null}}。\n\n开头：{head}\n\n结尾：{foot}"
)


async def _ask_model(pdf: LocalPdf) -> str | None:
    from ..llm import client

    page = pdf.pages[pdf.cover_pages] if len(pdf.pages) > pdf.cover_pages else ""
    if not page:
        return None
    res = await client.chat_json("structure", [{"role": "user", "content": _PROMPT.format(
        head=page[:500], foot=page[-200:])}], _Venue)
    name = clean_venue(res.value.venue if res.value else None)
    # the answer must be printed on the page (no invented journals)
    if not name or squash(name) not in squash(page):
        return None
    return name


async def annotate_venues(pdfs: list[LocalPdf], linked: set[str], *,
                          use_model: bool = False) -> None:
    """Fill doc.venue / venue_via / paper_type on every PDF; the model is
    asked only for readable, uncited PDFs no local rule could place."""
    ask: list[LocalPdf] = []
    for p in pdfs:
        d = p.doc
        d.paper_type = paper_type(d.title)  # type: ignore[assignment]
        if d.venue:
            d.venue_via = d.venue_via or ("cnki_cover" if d.source == "cnki_cover"
                                          else "cnki_citation")
            continue
        name, how = venue_from_traces(p)
        if name:
            d.venue, d.venue_via = name, how  # type: ignore[assignment]
        elif use_model and d.readable and d.id not in linked:
            ask.append(p)
    if not ask:
        return

    async def one(p: LocalPdf):
        try:
            name = await _ask_model(p)
        except Exception as e:  # noqa: BLE001 — a failed guess leaves it unknown
            log.warning("venue guess failed for %s: %s", p.doc.filename, e)
            return
        if name:
            p.doc.venue, p.doc.venue_via = name, "model"

    await asyncio.gather(*(one(p) for p in ask))


def match_target(pdf: LocalPdf, venue: str | None, entry: dict | None = None) -> str | None:
    """How ``pdf`` was recognised as a paper of ``venue`` (its venue_via,
    or "header"), None when it isn't one."""
    if not venue:
        return None
    if same_venue(pdf.doc.venue, venue) or (
            entry and any(same_venue(pdf.doc.venue, a) for a in [entry["name"], *entry.get("aliases", [])])):
        return pdf.doc.venue_via or "cnki_cover"
    if header_names(pdf, venue, entry):
        return "header"
    return None
