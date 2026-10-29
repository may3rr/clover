"""建立连接：参考文献条目 ↔ 文献文件夹里的 PDF，一对一。

Scoring, per (reference, PDF) pair:
- same DOI -> 100
- title: the entry's title against the PDF's extracted title, and
  whether it appears verbatim in the PDF's first pages (a cited paper
  prints its own title there — the most robust signal, it survives
  renamed files and missing metadata)
- the file name ("标题_作者.pdf") as a weaker title source
- first author found in the PDF metadata or first pages: required for
  an automatic link; a year off by more than one is a conflict

Pairs are assigned greedily by score, so a PDF never serves two entries.
Strong pairs link automatically; mid-band pairs go to the model as a
multiple-choice question (pick one of three PDFs or none) and every
model pick is marked ``review`` for the user's confirmation step.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable

from pydantic import BaseModel
from rapidfuzz import fuzz

from ..parse.links import latin_surname
from ..schema import Library, LibraryLink, Reference
from .scan import LocalPdf, filename_meta
from .text import squash
from .venue_match import annotate_venues, match_target

log = logging.getLogger(__name__)

AUTO = 90.0  # >= with author agreement: linked without asking
FLOOR = 60.0  # below: not a candidate at all
ASK = 70.0  # mid band [ASK, AUTO) without an author conflict -> the model
_MAX_TITLE = 200  # squashed chars compared against first pages
_MIN_TITLE = 6  # squashed chars; shorter titles ("Qwen Team") never match text
_ZH_NAME = re.compile(r"[一-鿿]{2,4}")


def _first_author_key(authors: list[str]) -> str:
    if not authors:
        return ""
    first = authors[0].strip()
    m = _ZH_NAME.search(first)
    return squash(m.group(0) if m else latin_surname(first))


def _title_score(ref: Reference, pdf: LocalPdf, head: str) -> tuple[float, str]:
    # a "title" that swallowed trailing text (author bios after the list) is
    # hopeless to align and costs seconds: no real title is this long
    t = squash(ref.title or "")[:_MAX_TITLE]
    if len(t) < _MIN_TITLE:
        return 0.0, "title"
    best, how = 0.0, "title"
    if pdf.doc.title and pdf.doc.source != "filename":
        best = fuzz.ratio(t, squash(pdf.doc.title))
    if len(t) >= 12 and t in head:
        best = max(best, 96.0)
    elif head and len(t) >= 12:
        # tolerate a line-break artefact or a subtitle difference
        # below FLOOR + 4 the pair is dropped anyway: the cutoff lets rapidfuzz
        # stop early instead of aligning every title against every first page
        best = max(best, fuzz.partial_ratio(t, head[:4000], score_cutoff=FLOOR + 4) - 4)
    fn_title, _ = filename_meta(pdf.doc.filename)
    fn = fuzz.ratio(t, squash(fn_title)) - 3  # file names are user-editable
    if fn > best:
        best, how = fn, "filename"
    return float(best), how


def score_pair(ref: Reference, pdf: LocalPdf, head: str | None = None) -> tuple[float, str, bool | None]:
    """(score 0-100, method, author agreement: True/False/None unknown)."""
    if head is None:
        head = squash(pdf.first_pages)
    if ref.doi and pdf.doc.doi and ref.doi.lower().rstrip(".") == pdf.doc.doi.lower():
        return 100.0, "doi", True
    score, how = _title_score(ref, pdf, head)
    key = _first_author_key(ref.authors)
    author: bool | None = None
    if key and len(key) >= 2:
        names = {_first_author_key([a]) for a in pdf.doc.authors}
        author = key in names or key in head[:3000]
    if ref.year and pdf.doc.year and abs(ref.year - pdf.doc.year) > 1:
        score -= 15  # a different edition / a different paper
    return score, how, author


class _Choice(BaseModel):
    choice: int  # 1-based candidate index, 0 = none of them


_PROMPT = (
    "下面是一条参考文献，以及用户文献文件夹里的若干候选 PDF（标题、作者、开头文字）。"
    "判断哪一个 PDF 就是这条参考文献所指的文献。只有确定是同一篇时才选择；"
    "同一主题的不同论文不算。只输出 JSON：{{\"choice\": 候选编号}}，都不是则 {{\"choice\": 0}}。\n\n"
    "参考文献：{ref}\n\n候选：\n{cands}"
)


async def _ask_model(ref: Reference, cands: list[LocalPdf]) -> LocalPdf | None:
    from ..llm.client import chat_json

    lines = []
    for k, p in enumerate(cands, 1):
        lines.append(f"[{k}] 标题：{p.doc.title or '未知'}；作者：{'，'.join(p.doc.authors[:4]) or '未知'}；"
                     f"开头：{p.first_pages[:200]}")
    res = await chat_json("structure", [{"role": "user", "content": _PROMPT.format(
        ref=ref.raw[:500], cands="\n".join(lines))}], _Choice)
    if res.value is None or not 1 <= res.value.choice <= len(cands):
        return None
    return cands[res.value.choice - 1]


async def link_library(
    refs: list[Reference], pdfs: list[LocalPdf], folder: str,
    *, use_model: bool = True, venue: str | None = None,
    guess_venues: bool = False, exemplar_ids: list[str] | None = None,
    manuscript_type: str = "research",
    on_stage: Callable[[str, int, int], None] | None = None,
) -> Library:
    """``guess_venues``: ask the model for the journal of uncited PDFs no
    local rule could place (needs ``use_model``). ``on_stage(stage, done,
    total)`` reports "link" (refs scored) and "ask" (model questions)."""
    note = on_stage or (lambda _s, _d, _t: None)
    heads = {p.doc.id: squash(p.first_pages) for p in pdfs}

    def _score_all() -> list[tuple[float, str, str, str, bool | None]]:
        # refs x PDFs fuzzy matching is CPU-bound: keep it off the event loop
        out = []
        for i, r in enumerate(refs, 1):
            for p in pdfs:
                s, how, author = score_pair(r, p, heads[p.doc.id])
                if s >= FLOOR:
                    out.append((s, r.id, p.doc.id, how, author))
            note("link", i, len(refs))
        return out

    pairs = await asyncio.to_thread(_score_all)
    pairs.sort(key=lambda x: -x[0])

    by_ref = {r.id: r for r in refs}
    by_doc = {p.doc.id: p for p in pdfs}
    links: dict[str, LibraryLink] = {}
    used: set[str] = set()
    pending: dict[str, list[str]] = {}  # ref -> mid-band candidate docs
    for s, rid, did, how, author in pairs:
        if rid in links or did in used:
            continue
        strong = s >= AUTO and author is not False and (author or s >= 95)
        if strong:
            links[rid] = LibraryLink(ref_id=rid, doc_id=did, method=how,
                                     score=round(min(s, 100.0), 1))
            used.add(did)
        elif s >= ASK and author is not False:
            pending.setdefault(rid, []).append(did)

    # the questions are independent: ask them side by side, then apply the
    # answers in order so one PDF is still linked to one reference only
    asks = [(rid, [by_doc[d] for d in dids if d not in used][:3])
            for rid, dids in pending.items() if rid not in links]
    asks = [(rid, c) for rid, c in asks if c]
    answers: dict[str, LocalPdf | None] = {}
    if use_model and asks:
        gate = asyncio.Semaphore(4)
        answered = 0

        async def one(rid: str, cands: list[LocalPdf]) -> None:
            nonlocal answered
            async with gate:
                try:
                    answers[rid] = await _ask_model(by_ref[rid], cands)
                except Exception:  # noqa: BLE001 — an unanswered question stays unlinked
                    answers[rid] = None
            answered += 1
            note("ask", answered, len(asks))

        note("ask", 0, len(asks))
        await asyncio.gather(*(one(rid, c) for rid, c in asks))

    for rid, _cands in asks:
        pick = answers.get(rid)
        if pick is None or pick.doc.id in used:
            continue
        s = next(x[0] for x in pairs if x[1] == rid and x[2] == pick.doc.id)
        links[rid] = LibraryLink(ref_id=rid, doc_id=pick.doc.id, method="llm",
                                 score=round(s, 1), status="review")
        used.add(pick.doc.id)

    final = [links[r.id] for r in refs if r.id in links]
    note("venue", 0, 0)
    await annotate_venues(pdfs, {x.doc_id for x in final},
                          use_model=use_model and guess_venues)
    return assemble(final, pdfs, folder, venue, exemplar_ids=exemplar_ids,
                    manuscript_type=manuscript_type)


def assemble(links: list[LibraryLink], pdfs: list[LocalPdf], folder: str,
             venue: str | None = None, *, exemplar_ids: list[str] | None = None,
             manuscript_type: str = "research",
             ) -> Library:
    """Library record from final links. The target venue is the one the
    user typed (none: no exemplars). Its uncited PDFs are the matches;
    the exemplars are ``exemplar_ids`` when the user picked them, else
    the matches of the manuscript's paper type."""
    from ..distribution.registry import resolve_target

    used = {x.doc_id for x in links}
    target = resolve_target(venue)
    venue, entry = target if target else (None, None)
    source = "user" if venue else None
    free = [p for p in pdfs if p.doc.id not in used and p.doc.readable]
    matches = []
    for p in free:
        how = match_target(p, venue, entry)
        if how:
            matches.append(p)
            if how == "header" and not p.doc.venue:
                p.doc.venue, p.doc.venue_via = venue, "header"
    if exemplar_ids is not None:
        free_ids = {p.doc.id for p in free}
        exemplars = [i for i in dict.fromkeys(exemplar_ids) if i in free_ids]
    else:
        exemplars = [p.doc.id for p in matches if p.doc.paper_type == manuscript_type]
    return Library(folder=folder, docs=[p.doc for p in pdfs], links=links,
                   exemplar_ids=exemplars, venue=venue or None, venue_source=source,
                   venue_match_ids=[p.doc.id for p in matches])
