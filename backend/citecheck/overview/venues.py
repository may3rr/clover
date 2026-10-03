"""Target venues and exemplar selection (overview stage, step 1).

The ACL Anthology publishes every paper of a venue with title, abstract
and an open PDF. We download a venue's recent volume pages once (cached
forever — a published volume doesn't change), rank its papers against
the manuscript's title + abstract with BM25 *locally*, and keep the few
closest as yardsticks. Nothing from the manuscript leaves the machine
in this step.
"""

from __future__ import annotations

import html as htmllib
import logging
import re
from dataclasses import dataclass

import httpx

from ..cache import Cache, make_key

log = logging.getLogger(__name__)

ANTHOLOGY = "https://aclanthology.org"


@dataclass(frozen=True)
class Venue:
    id: str
    name: str
    volume: str  # ACL Anthology volume pattern, {y} = year


VENUES: dict[str, Venue] = {
    v.id: v
    for v in (
        Venue("emnlp", "EMNLP", "{y}.emnlp-main"),
        Venue("acl", "ACL", "{y}.acl-long"),
        Venue("naacl", "NAACL", "{y}.naacl-long"),
        Venue("findings-emnlp", "Findings of EMNLP", "{y}.findings-emnlp"),
    )
}


@dataclass
class Candidate:
    id: str
    title: str
    abstract: str
    year: int

    @property
    def url(self) -> str:
        return f"{ANTHOLOGY}/{self.id}/"

    @property
    def pdf(self) -> str:
        return f"{ANTHOLOGY}/{self.id}.pdf"


_TITLE_RE = re.compile(
    r"<strong><a class=align-middle href=/([\w.-]+?\.\d+)/>(.*?)</a></strong>", re.S)
_ABS_RE = re.compile(
    r'id=abstract-([\w-]+?--\d+)><div class="card-body p-3 small">(.*?)</div>', re.S)


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def parse_volume(page: str, year: int) -> list[Candidate]:
    """Volume page HTML -> papers. Abstract ids use '--' for '.'; the
    frontmatter entry (*.0) is skipped."""
    abstracts = {k.replace("--", "."): _clean(v) for k, v in _ABS_RE.findall(page)}
    out = []
    for pid, title in _TITLE_RE.findall(page):
        if pid.endswith(".0"):
            continue
        out.append(Candidate(pid, _clean(title), abstracts.get(pid, ""), year))
    return out


async def load_volume(vol: str, year: int, client: httpx.AsyncClient,
                      cache: Cache) -> list[Candidate]:
    key = make_key("anthology-volume", vol)
    hit = cache.get(key)
    if isinstance(hit, list):
        return [Candidate(*row) for row in hit]
    try:
        r = await client.get(f"{ANTHOLOGY}/volumes/{vol}/", timeout=60)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("anthology volume %s unavailable: %s", vol, e)
        return []  # not cached — a future volume may simply not exist yet
    papers = parse_volume(r.text, year)
    if papers:
        cache.set(key, [[c.id, c.title, c.abstract, c.year] for c in papers])
    return papers


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def rank(candidates: list[Candidate], query: str, k: int = 3) -> list[Candidate]:
    """Top-k by BM25 over title (weighted twice) + abstract."""
    from rank_bm25 import BM25Okapi

    q = _tokens(query)
    if not candidates or not q:
        return []
    docs = [_tokens(f"{c.title} {c.title} {c.abstract}") for c in candidates]
    scores = BM25Okapi(docs).get_scores(q)
    order = sorted(range(len(candidates)), key=lambda i: -scores[i])
    return [candidates[i] for i in order[:k] if scores[i] > 0]


async def pick_exemplars(venue: Venue, query: str, years: list[int],
                         client: httpx.AsyncClient, cache: Cache,
                         k: int = 3) -> list[Candidate]:
    pool: list[Candidate] = []
    for y in years:
        pool += await load_volume(venue.volume.format(y=y), y, client, cache)
    return rank(pool, query, k)
