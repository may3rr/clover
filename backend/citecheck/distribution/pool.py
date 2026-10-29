"""对标范文池：目标期刊或会议的论文，原文已经在手。

Two sources, nothing searched for:

- cited: the manuscript's own references published in the target venue.
  A reference belongs to it when its journal / proceedings string (as
  structured, as on the verified Crossref / OpenAlex record, or on the
  linked PDF's cover) or its whole entry names the venue, or its DOI
  carries the venue's registered prefix. Names no rule could place go
  to the model as one multiple-choice question; the answer must come
  from the listed names. Text: the linked PDF in the reference folder,
  else the open-access PDF the verified record points at (arXiv
  included; an ACL Anthology DOI resolves to the Anthology's PDF).
  Without either the reference is listed, not counted.
- folder: uncited PDFs of the target venue in the reference folder
  (library.link.assemble; the user's selection on the confirmation page).

Papers of the other type (review vs research) than the manuscript are
listed but not counted, as on the confirmation page.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, Field

from ..cache import Cache, make_key
from ..library.scan import LocalPdf
from ..library.text import squash
from ..library.venue_match import clean_venue, paper_type
from ..schema import RefCheck, Reference
from .registry import doi_in_venue, mentions_venue
from .venue import ExemplarSource, from_pdf

log = logging.getLogger(__name__)

MAX_CITED = 12  # newest first; enough for a quartile, bounded downloads
_MAX_NAMES = 60
_PDF_DEADLINE = 30.0


@dataclass
class Pool:
    name: str
    sources: list[ExemplarSource] = field(default_factory=list)

    @property
    def n_cited(self) -> int:
        return sum(1 for s in self.sources if s.origin == "cited")


# ------------------------------------------------------- cited references


def _venue_strings(ref: Reference, check: RefCheck | None, pdf: LocalPdf | None) -> list[str]:
    out = [ref.venue, (check.matched or {}).get("venue") if check else None,
           pdf.doc.venue if pdf else None]
    return [clean_venue(x) for x in out if x and clean_venue(x)]


def rule_match(ref: Reference, check: RefCheck | None, pdf: LocalPdf | None,
               name: str, entry: dict | None) -> bool:
    if any(mentions_venue(v, name, entry) for v in _venue_strings(ref, check, pdf)):
        return True
    doi = ref.doi or ((check.matched or {}).get("doi") if check else None)
    return doi_in_venue(doi, entry) or mentions_venue(ref.raw, name, entry)


class _Pick(BaseModel):
    ids: list[int] = Field(default_factory=list)


_PROMPT = (
    "用户要投稿的期刊或会议是「{name}」{aliases}。下面是一篇稿件参考文献里出现的刊名或会议名，"
    "每行一个编号。找出其中和「{name}」是同一个期刊或同一个会议的编号，缩写、全称、"
    "中英文刊名、带年份或届次的会议名都算同一个；增刊、分会、Workshop、Findings 和"
    "名字相近的其他刊不算，除非「{name}」本身就是它。没有就输出空列表，不要猜。\n"
    "只输出 JSON：{{\"ids\": [编号]}}\n\n{lines}"
)


async def ask_model(name: str, entry: dict | None, names: list[str]) -> set[str]:
    """The listed names the model says are the target venue; any id
    outside the list is dropped (the answer can only pick, never add)."""
    from ..llm import client

    if not names:
        return set()
    aliases = f"（又名 {'、'.join(entry['aliases'][:4])}）" if entry and entry["aliases"] else ""
    lines = "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))
    res = await client.chat_json("structure", [{"role": "user", "content": _PROMPT.format(
        name=name, aliases=aliases, lines=lines)}], _Pick)
    if res.value is None:
        return set()
    return {names[i - 1] for i in res.value.ids if 1 <= i <= len(names)}


async def match_cited(refs: list[Reference], checks: dict[str, RefCheck],
                      local: dict[str, LocalPdf], name: str, entry: dict | None,
                      *, use_model: bool = False) -> list[Reference]:
    """References published in the target venue, in list order."""
    hit: set[str] = set()
    ask: dict[str, list[str]] = {}  # squashed name -> ref ids
    shown: dict[str, str] = {}
    for r in refs:
        strings = _venue_strings(r, checks.get(r.id), local.get(r.id))
        if rule_match(r, checks.get(r.id), local.get(r.id), name, entry):
            hit.add(r.id)
            continue
        for v in strings:
            k = squash(v)
            if k and "arxiv" not in k:
                ask.setdefault(k, []).append(r.id)
                shown.setdefault(k, v)
    if use_model and ask:
        names = [shown[k] for k in list(ask)[:_MAX_NAMES]]
        try:
            picked = await ask_model(name, entry, names)
        except Exception as e:  # noqa: BLE001 — rules stand on their own
            log.warning("venue choice question failed: %s", e)
            picked = set()
        for v in picked:
            hit.update(ask.get(squash(v), []))
    return [r for r in refs if r.id in hit]


# ------------------------------------------------------------- full text


async def fetch_pages(url: str, client: httpx.AsyncClient, cache: Cache) -> list[str] | None:
    """pypdf text per page of an open-access PDF, cached ([] = failed)."""
    import io

    from ..support.sources import _download_pdf

    key = make_key("pdfpages", url)
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    try:
        data = await asyncio.wait_for(_download_pdf(url, client), _PDF_DEADLINE)
    except (asyncio.TimeoutError, httpx.TransportError) as e:
        log.warning("exemplar pdf fetch failed %s: %r", url, e)
        return None  # transient: not cached, the next run tries again
    except httpx.HTTPError as e:
        log.warning("exemplar pdf fetch failed %s: %r", url, e)
        data = None
    pages: list[str] = []
    if data:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = await asyncio.to_thread(
                lambda: [p.extract_text() or "" for p in reader.pages])
        except Exception as e:  # noqa: BLE001
            log.warning("exemplar pdf parse failed %s: %s", url, e)
    cache.set(key, pages)
    return pages or None


_ACL_DOI = re.compile(r"^10\.18653/v1/(.+)$", re.I)


def _pdf_url(ref: Reference, check: RefCheck | None) -> str | None:
    """The open-access PDF: the verified record's, an ACL Anthology DOI's
    own PDF (10.18653/v1/D18-1259 -> aclanthology.org/D18-1259.pdf), or
    arXiv's."""
    m = (check.matched or {}) if check else {}
    if m.get("pdf_url"):
        return m["pdf_url"]
    for doi in (ref.doi, m.get("doi")):
        hit = _ACL_DOI.match(doi or "")
        if hit:
            aid = hit.group(1)
            # old-style ids are upper-case on the Anthology: D18-1259
            aid = aid[0].upper() + aid[1:] if re.fullmatch(r"[a-z]\d{2}-\d{4}", aid) else aid
            return f"https://aclanthology.org/{aid}.pdf"
    return f"https://arxiv.org/pdf/{m['arxiv_id']}" if m.get("arxiv_id") else None


async def cited_sources(cited: list[Reference], checks: dict[str, RefCheck],
                        local: dict[str, LocalPdf], *, manuscript_type: str,
                        client: httpx.AsyncClient | None, cache: Cache) -> list[ExemplarSource]:
    """``client`` None: no downloads (offline). Otherwise the PDFs come
    through a connection pool of their own — the support layer's
    downloads fill the shared one at this point of the run."""
    if client is None:
        return await _cited_sources(cited, checks, local, manuscript_type, None, cache)
    async with httpx.AsyncClient(follow_redirects=True) as own:
        return await _cited_sources(cited, checks, local, manuscript_type, own, cache)


async def _cited_sources(cited: list[Reference], checks: dict[str, RefCheck],
                         local: dict[str, LocalPdf], manuscript_type: str,
                         client: httpx.AsyncClient | None, cache: Cache
                         ) -> list[ExemplarSource]:
    gate = asyncio.Semaphore(4)
    # newest first: the venue's current shape, and a bounded number of downloads
    order = sorted(cited, key=lambda r: -(r.year or 0))

    async def one(k: int, r: Reference) -> ExemplarSource:
        check = checks.get(r.id)
        title = r.title or ((check.matched or {}).get("title") if check else None)
        kw = dict(origin="cited", ref_id=r.id, label=r.label)
        pdf = local.get(r.id)
        if pdf is not None and pdf.doc.readable:
            src = from_pdf(pdf, **kw)
            src.title, src.year = title or src.title, r.year or src.year
        else:
            url = _pdf_url(r, check)
            sid = "ref:" + hashlib.sha256((url or r.raw).encode()).hexdigest()[:16]
            src = ExemplarSource(id=sid, title=title, year=r.year, url=url, **kw)
            if k >= MAX_CITED:
                src.note = "范文已够，没有读取"
            elif url is None or client is None:
                src.note = "没有取得原文，未参与统计"
            else:
                async with gate:
                    src.raw_pages = await fetch_pages(url, client, cache)
                if not src.raw_pages:
                    src.note = "没有取得原文，未参与统计"
        if not src.note and k >= MAX_CITED:
            src.note = "范文已够，没有读取"
        if not src.note and paper_type(src.title) != manuscript_type:
            src.note = ("综述，与稿件类型不同，未参与统计" if manuscript_type == "research"
                        else "研究论文，与稿件类型不同，未参与统计")
        return src

    return list(await asyncio.gather(*(one(k, r) for k, r in enumerate(order))))


async def gather_pool(name: str, entry: dict | None, *, refs: list[Reference],
                      checks: list[RefCheck], local: dict[str, LocalPdf],
                      folder: list[LocalPdf], manuscript_type: str = "research",
                      client: httpx.AsyncClient | None = None, cache: Cache,
                      use_model: bool = False) -> Pool:
    """The target venue's papers with text at hand: cited references
    first, then the folder's uncited exemplars."""
    by_id = {c.ref_id: c for c in checks}
    refs = [r for r in refs if r.origin == "list"]
    cited = await match_cited(refs, by_id, local, name, entry, use_model=use_model)
    sources = await cited_sources(cited, by_id, local, manuscript_type=manuscript_type,
                                  client=client, cache=cache)
    seen = {s.id for s in sources}
    sources += [from_pdf(p) for p in folder if p.doc.id not in seen]
    return Pool(name, sources)


def shortfall_note(name: str, found: int, usable: int, need: int) -> str:
    """Why there is no benchmark, and what the author can do."""
    hint = "可以在文献文件夹放入该刊近期发表的论文后重新体检。"
    if found == 0:
        return f"参考文献和文献文件夹中没有找到《{name}》的论文，无法对标。{hint}"
    return (f"参考文献和文献文件夹中找到 {found} 篇《{name}》论文，其中 {usable} 篇能完成统计，"
            f"至少需要 {need} 篇才能对标。{hint}")
