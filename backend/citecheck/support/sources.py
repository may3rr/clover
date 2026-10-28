"""被引文献原文获取：开放全文 PDF 优先，其次摘要，都拿不到则 none。

- PDF: openAccessPdf / arXiv PDF, <=20MB, pypdf 提取，修复断词换行，
  全文文本进缓存；再用 rank-bm25 在约 3 句窗口上挑出与论断最相关的片段
  （excerpt <= ~2000 chars）。
- 摘要：OpenAlex/S2 的 abstract（Crossref JATS 去标签）或 arXiv API
  的 summary；arXiv API 调用全进程限速 >=3 秒一次。
- 拿不到 → source_kind=none，调用方不再问模型，直接 undetermined。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..cache import Cache, make_key
from ..config import get_settings
from ..refs.sources import abstract_ok, arxiv_throttle as _arxiv_throttle

log = logging.getLogger(__name__)

_MAX_PDF_BYTES = 20 * 1024 * 1024
_EXCERPT_LIMIT = 2000
_FULLTEXT_EXCERPT_LIMIT = 2500


@dataclass
class SourceText:
    kind: str  # abstract | fulltext | none
    excerpt: str | None
    title: str | None


def _fix_pdf_text(text: str) -> str:
    text = text.replace("-\n", "")  # de-hyphenate line breaks
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)  # join hard-wrapped lines
    return re.sub(r"\s{2,}", " ", text).strip()


_TAIL_HEADING = re.compile(
    r"\breferences\b|\bbibliography\b|参考文献", re.I
)


def _drop_reference_tail(text: str) -> str:
    """Cut the paper's own bibliography: the last References/Bibliography/
    参考文献 heading sitting in the second half of the document."""
    half = len(text) // 2
    last = None
    for m in _TAIL_HEADING.finditer(text):
        if m.start() >= half:
            last = m
    return text[: last.start()] if last else text


_REF_ENTRY_HINT = re.compile(
    r"arXiv preprint|in proceedings|advances in neural information|"
    r"\bneurips\b|\biclr\b|\bicml\b|et al\.?[,，]|\b\d{4}[a-z]?\.\s", re.I
)
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
# a run of "Firstname Lastname," entries is a reference list, not prose
_NAME_RUN_RE = re.compile(r"[A-Z][a-zA-Z'\-]+ [A-Z][a-zA-Z'\-]+,")
# bare 4-6 digit page numbers between entries ("… 2019. 6779 Yankai Lin, …")
_PAGE_NUM_RE = re.compile(r"(?<![\d.])\b\d{4,5}\b(?=\s+[A-Z][a-z])")


def _looks_like_ref_entry(window: str) -> bool:
    """Heuristic: a text window that is really a bibliography entry —
    dense year tokens, venue phrases, author-name runs, page numbers."""
    years = len(_YEAR_RE.findall(window))
    hints = len(_REF_ENTRY_HINT.findall(window))
    names = len(_NAME_RUN_RE.findall(window))
    pages = len(_PAGE_NUM_RE.findall(window))
    if years >= 2 or hints >= 2 or (years >= 1 and hints >= 1):
        return True
    if names >= 2 and (pages >= 1 or hints >= 1 or years >= 1):
        return True
    return names >= 3 and pages >= 1


# in-flight dedup: several claim/ref pairs can need the same PDF/abstract
# at once — without this every pair downloads it again (failures aren't
# otherwise deduplicated within a run)
_inflight: dict[str, asyncio.Task] = {}


async def _shared(key: str, factory) -> str | None:
    """Run factory() once per key; concurrent callers share the task."""
    if key in _inflight:
        return await _inflight[key]
    task = asyncio.create_task(factory())
    _inflight[key] = task
    try:
        return await task
    finally:
        _inflight.pop(key, None)


# Whole-download deadline. httpx timeouts are per read, so a host that
# trickles bytes could hold a PDF (and every judge waiting on it) for
# minutes; past the deadline the pair falls back to the abstract.
_PDF_DEADLINE = 20.0


async def _download_pdf(url: str, client: httpx.AsyncClient) -> bytes | None:
    # unreachable hosts fail at connect time instead of after 30s
    timeout = httpx.Timeout(30, connect=8)
    async with client.stream("GET", url, timeout=timeout) as resp:
        if resp.status_code != 200:
            return None
        cl = resp.headers.get("content-length")
        if cl and int(cl) > _MAX_PDF_BYTES:
            return None
        chunks: list[bytes] = []
        size = 0
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > _MAX_PDF_BYTES:
                return None
            chunks.append(chunk)
    return b"".join(chunks)


async def _fetch_pdf_uncached(
    url: str, client: httpx.AsyncClient
) -> str | None:
    """Download + parse; '' on a definitive failure (bad status, too big,
    unparseable), None on a timeout — transient, so not cached."""
    try:
        data = await asyncio.wait_for(_download_pdf(url, client), _PDF_DEADLINE)
    except asyncio.TimeoutError:
        log.warning("pdf fetch exceeded %.0fs, using the abstract: %s",
                    _PDF_DEADLINE, url)
        return None
    except httpx.HTTPError as e:
        log.warning("pdf fetch failed %s: %s", url, e)
        return ""
    if data is None:
        return ""
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        # pypdf is CPU-bound — run it in a thread so PDF parsing a big
        # paper doesn't stall the event loop for every other layer
        text = await asyncio.to_thread(
            lambda: "\n".join(
                (p.extract_text() or "") for p in reader.pages))
    except Exception as e:  # noqa: BLE001
        log.warning("pdf parse failed %s: %s", url, e)
        return ""
    return _drop_reference_tail(_fix_pdf_text(text))


async def _fetch_pdf_text(url: str, client: httpx.AsyncClient, cache: Cache) -> str | None:
    key = make_key("pdftext", url)
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    # dedup + cache '' so a failing PDF costs one fetch per run, once ever
    # (timeouts are not cached — the next run tries again)
    text = await _shared(f"pdf:{url}",
                         lambda: _fetch_pdf_uncached(url, client))
    if text is None:
        return None
    cache.set(key, text)
    return text or None


def _tokenize(text: str) -> list[str]:
    """Latin words as-is; Chinese runs as character bigrams (a run of
    ideographs has no spaces, so whole runs would never match)."""
    out: list[str] = []
    for tok in re.findall(r"[a-z0-9]+|[一-鿿]+", text.lower()):
        if "一" <= tok[0] <= "鿿" and len(tok) > 1:
            out += [tok[i:i + 2] for i in range(len(tok) - 1)]
        else:
            out.append(tok)
    return out


_ARXIV_STAMP = re.compile(r"arXiv:\d{4}\.\d{4,5}v\d+\s*\[[^\]]*\]\s*\d{1,2}\s+\w{3}\s+\d{4}")


def _bm25_excerpt(
    fulltext: str, claim: str, limit: int = _EXCERPT_LIMIT, head: int = 0,
    max_parts: int = 5,
) -> str:
    """Top-ranked ~3-sentence windows, concatenated up to `limit` chars.

    With ``head`` > 0 the paper's opening sentences (title, authors,
    abstract; about ``head`` chars) lead the excerpt, so the judge knows
    which work this is even when the windows are off target."""
    from rank_bm25 import BM25Okapi

    from .claims import split_sentences

    sents = [s.text for s in split_sentences(_ARXIV_STAMP.sub(" ", fulltext))]
    if not sents:
        return fulltext[:limit]
    lead: list[str] = []
    if head:
        while len(lead) < len(sents) and sum(map(len, lead)) < head:
            lead.append(sents[len(lead)])
    start = len(lead)
    windows = [(i, " ".join(sents[i : i + 3])) for i in range(start, len(sents))]
    # bibliography entries that survived the tail cut are not evidence
    windows = [(i, w) for i, w in windows if not _looks_like_ref_entry(w)]
    prefix = " ".join(lead)
    room = limit - len(prefix)
    if not windows or room <= 0:
        return (prefix or fulltext)[:limit]
    bm25 = BM25Okapi([_tokenize(w) for _, w in windows])
    scores = bm25.get_scores(_tokenize(claim))
    order = sorted(range(len(windows)), key=lambda k: -scores[k])
    parts: list[str] = []
    taken: list[int] = []
    used = 0
    for k in order:
        if scores[k] <= 0:
            break
        i, w = windows[k]
        # overlapping windows repeat sentences: keep the budget for new text
        if any(abs(i - j) < 3 for j in taken):
            continue
        parts.append(w)
        taken.append(i)
        used += len(w) + 1
        if used >= room or len(parts) >= max_parts:
            break
    if not parts:
        body = " ".join(sents[start:])
        return (f"{prefix}\n\n{body}" if prefix else body)[:limit]
    passages = " ".join(parts)
    return (f"{prefix}\n\n{passages}" if prefix else passages)[:limit]


async def _arxiv_fetch(params: dict, client: httpx.AsyncClient) -> str | None:
    """One arXiv API call: polite >=3s spacing (every attempt re-throttles —
    a retry inside arXiv's rate window just 429s again) and one retry.
    Returns the response text, or None on failure — callers must NOT cache
    None, a transient 429 would otherwise lose the abstract for the whole
    cache TTL."""
    for attempt in range(2):
        await _arxiv_throttle()
        try:
            resp = await client.get(
                "https://export.arxiv.org/api/query",
                params=params, timeout=15,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == 0:
                    await asyncio.sleep(3.0)
                    continue
                log.warning("arxiv api failed: HTTP %d", resp.status_code)
                return None
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as e:
            if attempt == 0:
                await asyncio.sleep(3.0)
                continue
            log.warning("arxiv api failed: %s", e)
            return None
    return None


async def _arxiv_summary_fetch(arxiv_id: str, client: httpx.AsyncClient) -> str | None:
    text = await _arxiv_fetch({"id_list": arxiv_id}, client)
    if text is None:
        return None
    m = re.search(r"<summary>(.*?)</summary>", text, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


async def _arxiv_summary(arxiv_id: str, client: httpx.AsyncClient, cache: Cache) -> str | None:
    key = make_key("arxiv_abs", arxiv_id)
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    summary = await _shared(f"ax:{arxiv_id}",
                            lambda: _arxiv_summary_fetch(arxiv_id, client))
    if summary is None:
        return None
    cache.set(key, summary)
    return summary or None


async def _arxiv_title_fetch(title: str, client: httpx.AsyncClient) -> str | None:
    text = await _arxiv_fetch({"search_query": f'ti:"{title}"', "max_results": 1},
                              client)
    if text is None:
        return None
    m = re.search(r"<entry>.*?<summary>(.*?)</summary>", text, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


async def _arxiv_title_search(
    title: str, client: httpx.AsyncClient, cache: Cache
) -> str | None:
    """Last-resort abstract: search arXiv by title, take the top entry's
    summary. Same >=3s process-wide throttle as other arXiv calls."""
    key = make_key("arxiv_title", title)
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    summary = await _shared(f"axt:{title}",
                            lambda: _arxiv_title_fetch(title, client))
    if summary is None:
        return None
    cache.set(key, summary)
    return summary or None


def _strip_jats(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


async def build_source(
    matched: dict | None,
    claim_text: str,
    *,
    cache: Cache | None = None,
    client: httpx.AsyncClient | None = None,
) -> SourceText:
    """matched = RefCheck.matched (title/abstract/pdf_url/arxiv_id)."""
    if not matched:
        return SourceText("none", None, None)
    title = matched.get("title")
    cache = cache or Cache(get_settings().cache_path)
    own_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        # the PDF download (slowest step) starts right away and overlaps
        # the abstract lookups below
        pdf_url = matched.get("pdf_url")
        if not pdf_url and matched.get("arxiv_id"):
            pdf_url = f"https://arxiv.org/pdf/{matched['arxiv_id']}"
        pdf_task = asyncio.create_task(
            _fetch_pdf_text(pdf_url, client, cache)) if pdf_url else None

        # gather abstract candidates up front: verified hit first, then
        # sibling records of the same work, then arXiv (id, then title)
        candidates = [matched.get("abstract")]
        candidates += matched.get("extra_abstracts") or []
        abstract = next(
            (a for a in candidates if abstract_ok(a)), None
        )
        if not abstract and matched.get("arxiv_id"):
            abstract = await _arxiv_summary(matched["arxiv_id"], client, cache)
            if not abstract_ok(abstract):
                abstract = None
        if not abstract and title:
            abstract = await _arxiv_title_search(title, client, cache)
            if not abstract_ok(abstract):
                abstract = None
        if abstract:
            abstract = _strip_jats(abstract)[:_EXCERPT_LIMIT]

        # 1. open-access full text: abstract + top BM25 passages
        if pdf_task is not None:
            fulltext = await pdf_task
            if fulltext:
                passages = _bm25_excerpt(fulltext, claim_text,
                                         _FULLTEXT_EXCERPT_LIMIT)
                excerpt = (
                    f"{abstract} {passages}" if abstract else passages
                )[:_FULLTEXT_EXCERPT_LIMIT]
                return SourceText("fulltext", excerpt, title)
        # 2. abstract only
        if abstract:
            return SourceText("abstract", abstract, title)
        return SourceText("none", None, title)
    finally:
        if own_client:
            await client.aclose()
