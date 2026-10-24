"""Async retrieval clients for Crossref / OpenAlex / Semantic Scholar / arXiv.

Every response is cached by (source, query). A source that errored or
timed out reports ``ok=False`` — verify.py treats that as "unavailable",
not "no hit" (AGENTS: 不确定就说不确定).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import weakref
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

from ..cache import Cache, make_key
from ..config import get_settings

log = logging.getLogger(__name__)

CROSSREF = "https://api.crossref.org"
OPENALEX = "https://api.openalex.org"
S2 = "https://api.semanticscholar.org"
ARXIV_API = "https://export.arxiv.org/api/query"

# One lock per event loop: an asyncio.Lock binds to the loop that first
# waits on it, so a module-level lock breaks the second asyncio.run() in a
# process (batch scripts, tests). The 3s spacing itself stays process-wide.
_arxiv_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = \
    weakref.WeakKeyDictionary()
_arxiv_last = 0.0


def _arxiv_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _arxiv_locks.get(loop)
    if lock is None:
        lock = _arxiv_locks[loop] = asyncio.Lock()
    return lock


async def arxiv_throttle() -> None:
    """Process-wide >=3s spacing between arXiv API calls (politeness rule;
    shared by verification and support-source lookups)."""
    global _arxiv_last
    async with _arxiv_lock():
        wait = 3.0 - (time.monotonic() - _arxiv_last)
        if wait > 0:
            await asyncio.sleep(wait)
        _arxiv_last = time.monotonic()


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


_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"
_WS = re.compile(r"\s+")


def parse_arxiv_feed(xml_text: str) -> list[dict]:
    """Parse an arXiv API Atom feed into normalized hit dicts."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    hits: list[dict] = []
    for e in root.findall(f"{{{_ATOM}}}entry"):
        idu = e.findtext(f"{{{_ATOM}}}id") or ""
        arxiv_id = re.sub(r"v\d+$", "", idu.rsplit("/", 1)[-1]) or None
        title = _WS.sub(" ", e.findtext(f"{{{_ATOM}}}title") or "").strip()
        published = e.findtext(f"{{{_ATOM}}}published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            _WS.sub(" ", (a.findtext(f"{{{_ATOM}}}name") or "")).strip()
            for a in e.findall(f"{{{_ATOM}}}author")
        ]
        summary = _WS.sub(
            " ", e.findtext(f"{{{_ATOM}}}summary") or "").strip()
        doi = e.findtext(f"{{{_ARXIV_NS}}}doi")
        hit: dict = {"source": "arxiv", "title": title or None,
                     "authors": authors, "year": year, "venue": "arXiv",
                     "doi": doi or None, "url": idu or None,
                     "abstract": summary or None,
                     "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}"
                     if arxiv_id else None,
                     "arxiv_id": arxiv_id, "alt_year": year}
        if not abstract_ok(hit["abstract"]):
            hit["abstract"] = None
        hits.append(hit)
    return hits


_openalex_budget_warned = False


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    """Seconds to wait after a 429: the server's Retry-After when given
    (capped), else exponential backoff."""
    ra = resp.headers.get("retry-after", "")
    try:
        return min(max(float(ra), 0.5), 8.0)
    except ValueError:
        return min(2.0 ** attempt, 8.0)

# Process-wide cooldown for rate-limited sources: a source that ran out of
# budget (429) stays skipped for the next runs in this server process too,
# instead of every run re-learning it with a retry/backoff cycle.
_COOLDOWN_S = 600.0
_cooldown_until: dict[str, float] = {}


class RetrievalClient:
    def __init__(self, cache: Cache | None = None):
        s = get_settings()
        # one semaphore per source: Crossref being slow must not hold
        # OpenAlex / S2 requests in the queue behind it
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._default_conc = s.retrieval.concurrency
        self._per_source = dict(s.retrieval.per_source)
        self._timeout = s.retrieval.timeout
        self._retries = s.retrieval.retries
        self._mailto = s.crossref_mailto
        # OPENALEX_API_KEY may hold a comma-separated list: requests round-
        # robin across the keys, and one that hits its daily budget is
        # dropped for the rest of the run (see the 429 handler in _do_get)
        self._openalex_keys = [
            k.strip() for k in (s.openalex_api_key or "").split(",") if k.strip()]
        self._openalex_rr = 0
        self._s2_key = s.s2_api_key
        self._cache = cache
        # per-source stats for meta.timings: calls / seconds / cache hits
        self.stats: dict[str, dict] = {}
        # circuit breaker: a source that answered with persistent 429 /
        # exhausted budget — or keeps timing out — is down for the rest
        # of this run; remaining calls fail fast instead of every one
        # burning the full retry loop (~45s at timeout=15, retries=2)
        now = time.monotonic()
        self._down: set[str] = {
            src for src, until in _cooldown_until.items() if until > now}
        self._consecutive_fails: dict[str, int] = {}
        # 429s per source since its last successful answer
        self._r429: dict[str, int] = {}
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": f"citecheck/0.1 (mailto:{self._mailto})"},
            follow_redirects=True,
        )

    def _sem(self, src: str) -> asyncio.Semaphore:
        sem = self._sems.get(src)
        if sem is None:
            sem = asyncio.Semaphore(
                self._per_source.get(src, self._default_conc))
            self._sems[src] = sem
        return sem

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "RetrievalClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _track(self, source: str, dt: float, cached: bool) -> None:
        st = self.stats.setdefault(source, {"calls": 0, "seconds": 0.0, "cached": 0})
        st["calls"] += 1
        st["seconds"] = round(st["seconds"] + dt, 3)
        if cached:
            st["cached"] += 1

    async def _get(
        self, url: str, params: dict, cache_key: str,
        headers: dict | None = None,
    ) -> SourceResult:
        src = (
            "crossref" if "crossref" in url
            else "openalex" if "openalex" in url
            else "s2" if "semanticscholar" in url
            else "arxiv" if "arxiv" in url
            else url
        )
        t0 = time.monotonic()
        if self._cache is not None:
            hit = self._cache.get(cache_key)
            if hit is not None:
                self._track(src, 0.0, cached=True)
                if isinstance(hit, dict) and "__error__" in hit:
                    return SourceResult(ok=False, error=hit["__error__"])
                if isinstance(hit, dict) and "__empty__" in hit:
                    return SourceResult(
                        ok=True, data=None, error=f"HTTP {hit['__empty__']}")
                return SourceResult(ok=True, data=hit)
        if src in self._down:
            self._track(src, 0.0, cached=False)
            return SourceResult(ok=False, error="source unavailable")
        r = await self._do_get(url, params, cache_key, headers, src)
        if not r.ok and ("429" in (r.error or "") or "budget" in (r.error or "")):
            self._down.add(src)
            # carry over to later runs only when the budget itself is gone
            # (OpenAlex budget message, S2's shared keyless pool); Crossref
            # throttling clears within seconds
            if "budget" in (r.error or "") or (src == "s2" and not self._s2_key):
                _cooldown_until[src] = time.monotonic() + _COOLDOWN_S
        self._track(src, time.monotonic() - t0, cached=False)
        return r

    def _note_result(self, src: str, ok: bool) -> None:
        """Two consecutive transport failures take the source down for
        this run — a host that times out repeatedly won't recover inside
        one pipeline run."""
        if ok:
            self._consecutive_fails[src] = 0
            return
        n = self._consecutive_fails.get(src, 0) + 1
        self._consecutive_fails[src] = n
        if n >= 2 and src not in self._down:
            self._down.add(src)
            log.warning("%s keeps failing — skipping it for the rest of "
                        "this run", src)

    async def _do_get(
        self, url: str, params: dict, cache_key: str,
        headers: dict | None = None, src: str = "",
    ) -> SourceResult:
        """Network path only — _get() already served cache hits."""
        last_err: str | None = None
        retried_429 = False
        for attempt in range(self._retries + 1):
            if src in self._down:
                return SourceResult(ok=False, error="source unavailable")
            try:
                async with self._sem(src):
                    if src in self._down:
                        return SourceResult(
                            ok=False, error="source unavailable")
                    resp = await self._client.get(
                        url, params=params, headers=headers)
                if resp.status_code == 429:
                    if src == "openalex" and "Insufficient budget" in resp.text:
                        # this key's daily budget is spent — drop it and
                        # retry immediately with the next configured key
                        dead = params.get("api_key")
                        if dead in self._openalex_keys:
                            self._openalex_keys.remove(dead)
                        if self._openalex_keys:
                            log.warning(
                                "an OpenAlex key ran out of budget — %d "
                                "key(s) left, retrying with the next one",
                                len(self._openalex_keys))
                            stripped = {
                                k: v for k, v in params.items()
                                if k not in ("api_key", "mailto")}
                            return await self._do_get(
                                url, self._openalex_params(stripped),
                                cache_key, headers, src)
                        global _openalex_budget_warned
                        if not _openalex_budget_warned:
                            _openalex_budget_warned = True
                            log.warning(
                                "OpenAlex rejected the request: %s — every "
                                "configured key is out of budget; treating "
                                "OpenAlex as unavailable.",
                                resp.text.strip()[:160])
                        return SourceResult(
                            ok=False, error="openalex budget exhausted")
                    # Crossref/OpenAlex 429 means "slow down" (too many
                    # concurrent requests), not "budget gone": back off as
                    # told and retry. Only a run of 429s with no success in
                    # between takes the source down for this run. S2 without
                    # a key shares one global pool — there a repeat 429 is
                    # the steady state, so it goes down at once.
                    n429 = self._r429.get(src, 0) + 1
                    self._r429[src] = n429
                    limit = 2 if src == "s2" else 6
                    if n429 >= limit or (src == "s2" and retried_429):
                        self._down.add(src)
                        log.warning(
                            "%s rate-limited — skipping it for the rest "
                            "of this run", src)
                        return SourceResult(ok=False, error="429")
                    retried_429 = True
                    await asyncio.sleep(_retry_after(resp, attempt))
                    last_err = "429"
                    continue
                if resp.status_code >= 500:
                    last_err = f"HTTP {resp.status_code}"
                    await asyncio.sleep(min(2**attempt, 4))
                    continue
                if 400 <= resp.status_code < 500:
                    # 4xx (non-429): the source answered — the record does
                    # not exist (404) or the query itself is invalid (400/
                    # 403, e.g. a DOI with illegal characters). Not a
                    # transport failure: no retry, no circuit-breaker
                    # count. Callers read ok=True + data=None as
                    # "responded, no result".
                    self._note_result(src, True)
                    # a definitive "no such record" — cache it like a hit
                    if self._cache is not None:
                        self._cache.set(
                            cache_key, {"__empty__": resp.status_code})
                    return SourceResult(
                        ok=True, data=None,
                        error=f"HTTP {resp.status_code}")
                resp.raise_for_status()
                self._r429[src] = 0
                data = resp.json()
                if self._cache is not None:
                    self._cache.set(cache_key, data)
                self._note_result(src, True)
                return SourceResult(ok=True, data=data)
            except (httpx.HTTPError, ValueError) as e:
                last_err = str(e)
                await asyncio.sleep(min(2**attempt, 4))
        self._note_result(src, False)
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
    def _openalex_params(self, params: dict) -> dict:
        params = dict(params)
        params["mailto"] = self._mailto
        if self._openalex_keys:
            params["api_key"] = self._openalex_keys[
                self._openalex_rr % len(self._openalex_keys)]
            self._openalex_rr += 1
        return params

    async def openalex_search(
        self, query: str, per_page: int = 5, year: int | None = None
    ) -> SourceResult:
        params = self._openalex_params({"search": query, "per-page": per_page})
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
            self._openalex_params({}),
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
        headers = {"x-api-key": self._s2_key} if self._s2_key else None
        r = await self._get(
            f"{S2}/graph/v1/paper/search", params,
            make_key("s2", "search", query, year) if year else make_key("s2", "search", query),
            headers=headers,
        )
        if r.ok and r.data:
            return SourceResult(
                ok=True, data=[_norm_hit("s2", w) for w in r.data.get("data", [])]
            )
        return r

    # -- arXiv ----------------------------------------------------------
    async def _arxiv_query(
        self, search_query: str, max_results: int,
        id_list: list[str] | None = None,
    ) -> SourceResult:
        """One raw arXiv API call. The Atom body is cached as
        {"xml": ...} so fixtures/tests can seed recorded feeds."""
        if "arxiv" in self._down:
            self._track("arxiv", 0.0, cached=False)
            return SourceResult(ok=False, error="source unavailable")
        params: dict = {"max_results": max_results}
        if id_list:
            params["id_list"] = ",".join(id_list)
            key = make_key("arxiv", "ids", params["id_list"])
        else:
            params["search_query"] = search_query
            key = make_key("arxiv", "xml", search_query, max_results)
        t0 = time.monotonic()
        if self._cache is not None:
            hit = self._cache.get(key)
            if isinstance(hit, dict) and "__error__" in hit:
                self._track("arxiv", 0.0, cached=True)
                return SourceResult(ok=False, error=hit["__error__"])
            if isinstance(hit, dict) and "xml" in hit:
                self._track("arxiv", 0.0, cached=True)
                return SourceResult(ok=True, data=hit["xml"])
        await arxiv_throttle()
        # one retry (like the other sources): the throttle lock already
        # enforces the >=3s gap, backoff sleeps on top of it. A single
        # failure only counts toward the circuit breaker (_note_result) —
        # two consecutive fails take arXiv down for this run.
        xml_text: str | None = None
        last_err: str | None = None
        for attempt in range(2):
            try:
                async with self._sem("arxiv"):
                    resp = await self._client.get(ARXIV_API, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = f"HTTP {resp.status_code}"
                    if attempt == 0:
                        await asyncio.sleep(min(2**attempt, 4))
                        continue
                    break
                resp.raise_for_status()
                xml_text = resp.text
                break
            except httpx.HTTPError as e:
                last_err = str(e)
                if attempt == 0:
                    await asyncio.sleep(min(2**attempt, 4))
                    continue
                break
        self._track("arxiv", time.monotonic() - t0, cached=False)
        if xml_text is None:
            self._note_result("arxiv", False)
            return SourceResult(ok=False, error=last_err)
        self._note_result("arxiv", True)
        if self._cache is not None:
            self._cache.set(key, {"xml": xml_text})
        return SourceResult(ok=True, data=xml_text)

    async def arxiv_by_ids(self, ids: list[str]) -> SourceResult:
        """Direct lookup of explicit arXiv identifiers (new-style
        ``YYMM.NNNNN``), many per request — the cheapest exact check
        for preprint references."""
        ids = sorted(set(ids))
        if not ids:
            return SourceResult(ok=True, data=[])
        r = await self._arxiv_query("", len(ids), id_list=ids)
        if not r.ok:
            return r
        return SourceResult(ok=True, data=parse_arxiv_feed(r.data))

    async def arxiv_search(
        self, title: str, author: str | None = None, max_results: int = 5
    ) -> SourceResult:
        """Title search on arXiv: exact ti:"phrase" first, then a looser
        ANDed ti:word query when the phrase finds nothing."""
        q = f'ti:"{title}"'
        if author:
            q += f' AND au:"{author}"'
        r = await self._arxiv_query(q, max_results)
        if not r.ok:
            return r
        hits = parse_arxiv_feed(r.data)
        if not hits and not author:
            return await self.arxiv_loose_search(title, max_results)
        return SourceResult(ok=True, data=hits)

    async def arxiv_loose_search(
        self, title: str, author: str | None = None, max_results: int = 5
    ) -> SourceResult:
        """Loose ANDed ti:word query (no phrase); used as the per-ref
        fallback after a batched phrase lookup finds nothing. Head words
        only: preprints retitle the tail for the venue version
        ('... o1-Like LLMs' -> '... Long Reasoning Models') and one
        renamed tail word in the AND kills the whole query."""
        words = [w for w in re.findall(r"[A-Za-z0-9]+", title)
                 if len(w) > 2][:5]
        if len(words) <= 1 and not author:
            return SourceResult(ok=True, data=[])
        q = " AND ".join(f"ti:{w}" for w in words)
        if author:
            q += f' AND au:"{author}"'
        r = await self._arxiv_query(q, max_results)
        if not r.ok:
            return r
        return SourceResult(ok=True, data=parse_arxiv_feed(r.data))

    async def arxiv_search_batch(
        self, titles: list[str], max_results: int = 10
    ) -> SourceResult:
        """One request covering several refs: ti:"a" OR ti:"b" … .
        Callers match entries back per ref by title similarity. A single
        title produces the same ti:"phrase" query as arxiv_search."""
        titles = [t for t in titles if t]
        if not titles:
            return SourceResult(ok=True, data=[])
        if len(titles) == 1:
            q = f'ti:"{titles[0]}"'
            n = max_results
        else:
            q = " OR ".join(f'ti:"{t}"' for t in titles)
            n = max(max_results, 3 * len(titles))
        r = await self._arxiv_query(q, n)
        if not r.ok:
            return r
        return SourceResult(ok=True, data=parse_arxiv_feed(r.data))
