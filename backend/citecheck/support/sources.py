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


async def _fetch_pdf_text(url: str, client: httpx.AsyncClient, cache: Cache) -> str | None:
    key = make_key("pdftext", url)
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    try:
        async with client.stream("GET", url, timeout=30) as resp:
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
        data = b"".join(chunks)
    except httpx.HTTPError as e:
        log.warning("pdf fetch failed %s: %s", url, e)
        return None
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:  # noqa: BLE001
        log.warning("pdf parse failed %s: %s", url, e)
        return None
    text = _drop_reference_tail(_fix_pdf_text(text))
    cache.set(key, text)
    return text or None


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9一-鿿]+", text.lower())


def _bm25_excerpt(fulltext: str, claim: str, limit: int = _EXCERPT_LIMIT) -> str:
    """Top-ranked ~3-sentence windows, concatenated up to `limit` chars."""
    from rank_bm25 import BM25Okapi

    from .claims import split_sentences

    sents = [s.text for s in split_sentences(fulltext)]
    if not sents:
        return fulltext[:limit]
    windows = [" ".join(sents[i : i + 3]) for i in range(len(sents))]
    # bibliography entries that survived the tail cut are not evidence
    windows = [w for w in windows if not _looks_like_ref_entry(w)]
    if not windows:
        return fulltext[:limit]
    bm25 = BM25Okapi([_tokenize(w) for w in windows])
    scores = bm25.get_scores(_tokenize(claim))
    order = sorted(range(len(windows)), key=lambda i: -scores[i])
    parts: list[str] = []
    used = 0
    for i in order:
        if scores[i] <= 0:
            break
        w = windows[i]
        parts.append(w)
        used += len(w) + 1
        if used >= limit or len(parts) >= 5:
            break
    return " ".join(parts)[:limit] if parts else fulltext[:limit]


async def _arxiv_summary(arxiv_id: str, client: httpx.AsyncClient, cache: Cache) -> str | None:
    key = make_key("arxiv_abs", arxiv_id)
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    await _arxiv_throttle()
    try:
        resp = await client.get(
            "https://export.arxiv.org/api/query",
            params={"id_list": arxiv_id},
            timeout=15,
        )
        resp.raise_for_status()
        m = re.search(r"<summary>(.*?)</summary>", resp.text, re.S)
        summary = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    except httpx.HTTPError as e:
        log.warning("arxiv api failed %s: %s", arxiv_id, e)
        return None
    cache.set(key, summary or "")
    return summary


async def _arxiv_title_search(
    title: str, client: httpx.AsyncClient, cache: Cache
) -> str | None:
    """Last-resort abstract: search arXiv by title, take the top entry's
    summary. Same >=3s process-wide throttle as other arXiv calls."""
    key = make_key("arxiv_title", title)
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    await _arxiv_throttle()
    try:
        resp = await client.get(
            "https://export.arxiv.org/api/query",
            params={"search_query": f'ti:"{title}"', "max_results": 1},
            timeout=15,
        )
        resp.raise_for_status()
        m = re.search(r"<entry>.*?<summary>(.*?)</summary>", resp.text, re.S)
        summary = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    except httpx.HTTPError as e:
        log.warning("arxiv title search failed: %s", e)
        return None
    cache.set(key, summary or "")
    return summary


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
        pdf_url = matched.get("pdf_url")
        if not pdf_url and matched.get("arxiv_id"):
            pdf_url = f"https://arxiv.org/pdf/{matched['arxiv_id']}"
        if pdf_url:
            fulltext = await _fetch_pdf_text(pdf_url, client, cache)
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
