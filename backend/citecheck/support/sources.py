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

log = logging.getLogger(__name__)

_MAX_PDF_BYTES = 20 * 1024 * 1024
_EXCERPT_LIMIT = 2000

_arxiv_lock = asyncio.Lock()
_arxiv_last = 0.0


@dataclass
class SourceText:
    kind: str  # abstract | fulltext | none
    excerpt: str | None
    title: str | None


async def _arxiv_throttle() -> None:
    """Process-wide >=3s spacing between arXiv API calls."""
    global _arxiv_last
    async with _arxiv_lock:
        wait = 3.0 - (time.monotonic() - _arxiv_last)
        if wait > 0:
            await asyncio.sleep(wait)
        _arxiv_last = time.monotonic()


def _fix_pdf_text(text: str) -> str:
    text = text.replace("-\n", "")  # de-hyphenate line breaks
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)  # join hard-wrapped lines
    return re.sub(r"\s{2,}", " ", text).strip()


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
    text = _fix_pdf_text(text)
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
        # 1. open-access full text
        pdf_url = matched.get("pdf_url")
        if not pdf_url and matched.get("arxiv_id"):
            pdf_url = f"https://arxiv.org/pdf/{matched['arxiv_id']}"
        if pdf_url:
            fulltext = await _fetch_pdf_text(pdf_url, client, cache)
            if fulltext:
                return SourceText("fulltext", _bm25_excerpt(fulltext, claim_text), title)
        # 2. abstract (OpenAlex/S2 already normalized; Crossref JATS; arXiv)
        abstract = matched.get("abstract")
        if not abstract and matched.get("arxiv_id"):
            abstract = await _arxiv_summary(matched["arxiv_id"], client, cache)
        if abstract:
            abstract = _strip_jats(abstract)[:_EXCERPT_LIMIT]
            return SourceText("abstract", abstract, title)
        return SourceText("none", None, title)
    finally:
        if own_client:
            await client.aclose()
