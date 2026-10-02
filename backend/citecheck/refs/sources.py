"""Async retrieval clients for Crossref / OpenAlex / Semantic Scholar.

Every response is cached by (source, query). A source that errored or
timed out reports ``ok=False`` — verify.py treats that as "unavailable",
not "no hit" (AGENTS: 不确定就说不确定).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..cache import Cache, make_key
from ..config import get_settings

log = logging.getLogger(__name__)

CROSSREF = "https://api.crossref.org"
OPENALEX = "https://api.openalex.org"
S2 = "https://api.semanticscholar.org"


@dataclass
class SourceResult:
    ok: bool
    data: Any = None
    error: str | None = None


_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9a-z.\-/]+)", re.I)


def _arxiv_year(arxiv_id: str | None) -> int | None:
    """Publication year encoded in an arXiv id (YYMM prefix, old or new style)."""
    if not arxiv_id:
        return None
    m = re.match(r"(?:[a-z\-]+(?:\.[A-Z]{2})?/)?(\d{2})(\d{2})", arxiv_id)
    if not m:
        return None
    yy = int(m.group(1))
    return 1900 + yy if yy >= 91 else 2000 + yy


_META_RE = re.compile(
    r"proceedings of|in proceedings|\bpp?\.?\s*\d|\bvol\.?\s*\d|\bisbn\b", re.I
)
_NAME_GROUP_RE = re.compile(r"[A-Z][A-Za-z\-]+(?: [A-Z][A-Za-z\-]*)+[,.]")


def abstract_ok(a: str | None) -> bool:
    """Quality gate for metadata-source abstracts. Rejects short strings
    and front-matter junk (author lists, 'Proceedings of …', vol/pages)
    that sources sometimes deposit in the abstract field."""
    if not a:
        return False
    s = a.strip()
    if len(s) < 150:
        return False
    head = s[:200]
    if _META_RE.search(head):
        return False
    if len(_NAME_GROUP_RE.findall(head)) >= 3:
        return False
    return True


def _openalex_abstract(work: dict) -> str | None:
    inv = work.get("abstract_inverted_index")
    if not inv:
        return None
    positions: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def _norm_hit(source: str, raw: dict) -> dict:
    """Normalize a source-specific record to the matched-dict shape that
    T3 also consumes (abstract / pdf_url / arxiv_id)."""
    hit: dict = {"source": source, "title": None, "authors": [], "year": None,
                 "venue": None, "doi": None, "url": None, "abstract": None,
                 "pdf_url": None, "arxiv_id": None, "alt_year": None}
    if source == "crossref":
        titles = raw.get("title") or []
        hit["title"] = titles[0] if titles else None
        hit["authors"] = [
            f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
            for a in raw.get("author", [])
        ]
        for key in ("published-print", "published-online", "issued"):
            dp = raw.get(key, {}).get("date-parts")
            if dp and dp[0] and dp[0][0]:
                hit["year"] = dp[0][0]
                break
        venue = raw.get("container-title") or []
        hit["venue"] = venue[0] if venue else None
        hit["doi"] = raw.get("DOI")
        hit["url"] = raw.get("URL")
        # Crossref deposits arXiv preprints as 10.48550/arXiv.<id> with the
        # deposit date — the encoded id gives the real preprint year
        if hit["doi"] and str(hit["doi"]).startswith("10.48550/arXiv."):
            hit["arxiv_id"] = str(hit["doi"]).split("arXiv.", 1)[-1]
    elif source == "openalex":
        hit["title"] = raw.get("title") or raw.get("display_name")
        hit["authors"] = [
            a.get("author", {}).get("display_name", "")
            for a in raw.get("authorships", [])
        ]
        hit["year"] = raw.get("publication_year")
        loc = raw.get("primary_location") or {}
        hit["venue"] = (loc.get("source") or {}).get("display_name")
        hit["doi"] = (raw.get("doi") or "").replace("https://doi.org/", "") or None
        hit["url"] = raw.get("id")
        hit["abstract"] = _openalex_abstract(raw)
        oa = raw.get("best_oa_location") or {}
        hit["pdf_url"] = oa.get("pdf_url")
        ids = raw.get("ids") or {}
        if ids.get("arxiv"):
            hit["arxiv_id"] = ids["arxiv"].rsplit("/", 1)[-1]
        elif hit["doi"] and str(hit["doi"]).startswith("10.48550/arXiv."):
            hit["arxiv_id"] = str(hit["doi"]).split("arXiv.", 1)[-1]
        if not hit["arxiv_id"]:
            # reprints/versions often link the arXiv preprint via locations
            for loc in raw.get("locations") or []:
                m = _ARXIV_URL_RE.search(loc.get("landing_page_url") or "")
                if m:
                    hit["arxiv_id"] = re.sub(r"v\d+$", "", m.group(1))
                    break
        if not hit["pdf_url"]:
            for loc in raw.get("locations") or []:
                if loc.get("pdf_url"):
                    hit["pdf_url"] = loc["pdf_url"]
                    break
    elif source == "s2":
        hit["title"] = raw.get("title")
        hit["authors"] = [a.get("name", "") for a in raw.get("authors", [])]
        hit["year"] = raw.get("year")
        hit["venue"] = raw.get("venue")
        ext = raw.get("externalIds") or {}
        hit["doi"] = ext.get("DOI")
        hit["arxiv_id"] = ext.get("ArXiv")
        hit["url"] = raw.get("url")
        hit["abstract"] = raw.get("abstract")
        pdf = raw.get("openAccessPdf") or {}
        hit["pdf_url"] = pdf.get("url")
    hit["alt_year"] = _arxiv_year(hit["arxiv_id"])
    if not abstract_ok(hit["abstract"]):
        hit["abstract"] = None
    return hit


class RetrievalClient:
    def __init__(self, cache: Cache | None = None):
        s = get_settings()
        self._sem = asyncio.Semaphore(s.retrieval.concurrency)
        self._timeout = s.retrieval.timeout
        self._retries = s.retrieval.retries
        self._mailto = s.crossref_mailto
        self._cache = cache
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": f"citecheck/0.1 (mailto:{self._mailto})"},
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "RetrievalClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _get(self, url: str, params: dict, cache_key: str) -> SourceResult:
        if self._cache is not None:
            hit = self._cache.get(cache_key)
            if isinstance(hit, dict) and "__error__" in hit:
                return SourceResult(ok=False, error=hit["__error__"])
            if hit is not None:
                return SourceResult(ok=True, data=hit)
        last_err: str | None = None
        for attempt in range(self._retries + 1):
            try:
                async with self._sem:
                    resp = await self._client.get(url, params=params)
                if resp.status_code == 429:
                    await asyncio.sleep(2**attempt)
                    last_err = "429"
                    continue
                if resp.status_code >= 500:
                    last_err = f"HTTP {resp.status_code}"
                    continue
                if resp.status_code == 404:
                    return SourceResult(ok=True, data=None, error="404")
                resp.raise_for_status()
                data = resp.json()
                if self._cache is not None:
                    self._cache.set(cache_key, data)
                return SourceResult(ok=True, data=data)
            except (httpx.HTTPError, ValueError) as e:
                last_err = str(e)
                await asyncio.sleep(min(2**attempt, 4))
        return SourceResult(ok=False, error=last_err)

    # -- Crossref ------------------------------------------------------
    async def crossref_work(self, doi: str) -> SourceResult:
        r = await self._get(
            f"{CROSSREF}/works/{doi}",
            {"mailto": self._mailto},
            make_key("crossref", "work", doi.lower()),
        )
        if r.ok and r.data:
            return SourceResult(ok=True, data=_norm_hit("crossref", r.data["message"]))
        return r

    async def crossref_search(
        self, query: str, rows: int = 5, year: int | None = None,
        author: str | None = None,
    ) -> SourceResult:
        params: dict = {
            "query.bibliographic": query, "rows": rows, "mailto": self._mailto
        }
        if author:
            params["query.author"] = author
        if year:
            params["filter"] = (
                f"from-pub-date:{year - 1}-01-01,until-pub-date:{year + 1}-12-31"
            )
        key = (
            make_key("crossref", "search", query, year, author)
            if author
            else make_key("crossref", "search", query, year)
            if year
            else make_key("crossref", "search", query)
        )
        r = await self._get(f"{CROSSREF}/works", params, key)
        if r.ok and r.data:
            items = r.data.get("message", {}).get("items", [])
            return SourceResult(ok=True, data=[_norm_hit("crossref", w) for w in items])
        return r

    # -- OpenAlex ------------------------------------------------------
    async def openalex_search(
        self, query: str, per_page: int = 5, year: int | None = None
    ) -> SourceResult:
        params: dict = {
            "search": query, "per-page": per_page, "mailto": self._mailto
        }
        if year:
            params["filter"] = f"publication_year:{year - 1}-{year + 1}"
        r = await self._get(
            f"{OPENALEX}/works", params,
            make_key("openalex", "search", query, year) if year else make_key("openalex", "search", query),
        )
        if r.ok and r.data:
            return SourceResult(
                ok=True, data=[_norm_hit("openalex", w) for w in r.data.get("results", [])]
            )
        return r

    async def openalex_doi(self, doi: str) -> SourceResult:
        r = await self._get(
            f"{OPENALEX}/works/doi:{doi}",
            {"mailto": self._mailto},
            make_key("openalex", "doi", doi.lower()),
        )
        if r.ok and r.data:
            return SourceResult(ok=True, data=_norm_hit("openalex", r.data))
        return r

    # -- Semantic Scholar ----------------------------------------------
    async def s2_search(
        self, query: str, limit: int = 5, year: int | None = None
    ) -> SourceResult:
        fields = "title,authors,year,externalIds,abstract,openAccessPdf,venue,url"
        params: dict = {"query": query, "limit": limit, "fields": fields}
        if year:
            params["year"] = f"{year - 1}-{year + 1}"
        r = await self._get(
            f"{S2}/graph/v1/paper/search", params,
            make_key("s2", "search", query, year) if year else make_key("s2", "search", query),
        )
        if r.ok and r.data:
            return SourceResult(
                ok=True, data=[_norm_hit("s2", w) for w in r.data.get("data", [])]
            )
        return r
