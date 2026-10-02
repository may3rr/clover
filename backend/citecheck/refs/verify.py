"""真实性核验：每条参考文献是否真的存在、字段是否一致。

Status semantics (PLAN T2):
- verified: title、首作者、年份都对上；
- mismatch: 找到了这篇文献，但作者/年份/DOI 有出入；
- not_found: 英文文献，三个源都真正响应且都没有匹配；
- unverifiable: 中文文献查不到，或任一源不可用导致无法完成核验。

A source that errored/timed out is "unavailable", never "no hit".
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata

from rapidfuzz import fuzz

from ..schema import Anchor, Finding, Paragraph, RefCheck, Reference
from .sources import RetrievalClient, SourceResult
from .structure import complete_reference_fields

log = logging.getLogger(__name__)

_TITLE_MIN = 92.0
_SURNAME_MIN = 85.0
_SOURCES = ("crossref", "openalex", "s2")

_CJK = re.compile(r"[一-鿿]")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[^a-z0-9一-鿿]+", " ", s).strip()


def _surname(name: str, *, display_order: bool = False) -> str:
    """Surname from 'Surname, I.' / 'Vaswani A' / 'Ashish Vaswani' / 中文名.

    display_order=True treats bare 'First Last' as given-name-first (the
    format Crossref author lists and OpenAlex/S2 display names use).
    """
    n = (name or "").strip()
    if not n:
        return ""
    zh = _CJK.search(n)
    if zh:
        return n[zh.start()]  # Chinese surname = first character
    if "," in n:
        return n.split(",", 1)[0].strip()
    tokens = n.split()
    return tokens[-1] if display_order else tokens[0]


def _ref_surname(ref: Reference) -> str:
    return _surname(ref.authors[0]) if ref.authors else ""


def _hit_surname(hit: dict) -> str:
    authors = hit.get("authors") or []
    return _surname(authors[0], display_order=True) if authors else ""


async def _gather_hits(
    ref: Reference, client: RetrievalClient
) -> tuple[list[dict], set[str], bool]:
    """Return (hits, sources_that_responded, doi_resolved_to_other)."""
    hits: list[dict] = []
    responded: set[str] = set()
    doi_other = False

    if ref.doi:
        doi_results = await asyncio.gather(
            client.crossref_work(ref.doi), client.openalex_doi(ref.doi)
        )
        for src, r in zip(("crossref", "openalex"), doi_results):
            if not r.ok:
                continue
            responded.add(src)
            if r.data:  # 404 -> data None: resolved endpoint, no work
                hits.append(r.data)
        if not hits:
            # DOI didn't resolve anywhere -> fall back to title search
            title_hits, title_responded = await _title_hits(ref, client)
            hits += title_hits
            responded |= title_responded
    else:
        title_hits, title_responded = await _title_hits(ref, client)
        hits += title_hits
        responded |= title_responded
    return hits, responded, doi_other


async def _title_hits(ref: Reference, client: RetrievalClient) -> tuple[list[dict], set[str]]:
    query = ref.title or ref.raw[:200]
    calls = [
        client.crossref_search(query),
        client.openalex_search(query),
        client.s2_search(query),
    ]
    # a second, year-filtered pass: canonical records (e.g. the 2017
    # Transformer paper) can be pushed out of search results by later
    # same-titled works
    if ref.year:
        calls += [
            client.crossref_search(query, year=ref.year),
            client.openalex_search(query, year=ref.year),
            client.s2_search(query, year=ref.year),
        ]
        srcs = _SOURCES + _SOURCES
    else:
        srcs = _SOURCES
    results = await asyncio.gather(*calls)
    hits: list[dict] = []
    responded: set[str] = set()
    for src, r in zip(srcs, results):
        if not r.ok:
            continue
        responded.add(src)
        hits += r.data or []
    return hits, responded


async def _author_hits(
    ref: Reference, client: RetrievalClient
) -> list[dict]:
    """Targeted last pass: a different work sharing the same title can
    displace the real record in broad title search (e.g. 'Attention is
    all you need' -> Mineault 2021). Search title + first-author surname
    to pull the real record back into the candidate pool."""
    surname = _ref_surname(ref)
    if not (ref.title and surname):
        return []
    calls = [
        client.crossref_search(ref.title, author=surname),
        client.openalex_search(f"{ref.title} {surname}"),
        client.s2_search(f"{ref.title} {surname}"),
    ]
    if ref.year:
        calls += [
            client.crossref_search(ref.title, year=ref.year, author=surname),
            client.openalex_search(f"{ref.title} {surname}", year=ref.year),
            client.s2_search(f"{ref.title} {surname}", year=ref.year),
        ]
    results = await asyncio.gather(*calls)
    hits: list[dict] = []
    for r in results:
        if r.ok:
            hits += r.data or []
    return hits


def _evaluate(ref: Reference, hit: dict) -> list[str]:
    """Field-level issues for a title-matched hit; empty = verified."""
    issues: list[str] = []
    ref_surname = _ref_surname(ref)
    hit_surname = _hit_surname(hit)
    # CJK vs latin surname comparison is unreliable (pinyin order varies);
    # only flag when both sides are the same script
    if ref_surname and hit_surname and bool(_CJK.search(ref_surname)) == bool(
        _CJK.search(hit_surname)
    ):
        if _CJK.search(ref_surname):
            ok = hit_surname.startswith(ref_surname) or ref_surname.startswith(hit_surname)
        else:
            ok = fuzz.ratio(_norm(ref_surname), _norm(hit_surname)) >= _SURNAME_MIN
        if not ok:
            issues.append(
                f"首作者不一致：文中写 {ref.authors[0]}，数据库记录为 {hit['authors'][0]}"
            )
    if ref.year and hit.get("year"):
        # a reprint's record year can postdate the work; the arXiv version's
        # year (alt_year) is an acceptable match too
        years = [y for y in (hit["year"], hit.get("alt_year")) if y]
        if all(abs(int(y) - ref.year) > 1 for y in years):
            issues.append(
                f"年份不一致：文中写 {ref.year}，数据库记录为 {hit['year']}"
            )
    if ref.doi and hit.get("doi") and ref.doi.lower() != str(hit["doi"]).lower():
        issues.append(f"DOI 不一致：文中写 {ref.doi}，数据库记录为 {hit['doi']}")
    return issues


def _finding(ref: Reference, check: RefCheck, para_len: int) -> Finding:
    anchor = Anchor(paragraph_id=ref.paragraph_id or "", start=0, end=para_len)
    if check.status == "not_found":
        return Finding(
            id="", layer="authenticity", severity="high", anchor=anchor,
            title="未能在数据库中找到这篇文献",
            detail="依据：Crossref、OpenAlex、Semantic Scholar 均未检索到标题或作者相符的记录。\n"
                   "建议：核对文献的作者、年份、标题和 DOI，确认是否误引或编造。",
            refs=[ref.id],
        )
    if check.status == "mismatch":
        return Finding(
            id="", layer="authenticity", severity="medium", anchor=anchor,
            title="文献信息与数据库记录不一致",
            detail="依据：" + "；".join(check.issues) + "。\n"
                   "建议：核对文献的作者、年份、DOI 等字段。",
            refs=[ref.id],
        )
    return Finding(
        id="", layer="authenticity", severity="low", anchor=anchor,
        title="暂时无法核验这篇文献",
        detail="依据：" + "；".join(check.issues or ["检索服务暂不可用"]) + "。\n"
               "建议：稍后重新体检，或人工确认该文献是否真实存在。",
        refs=[ref.id],
    )


async def _verify_one(
    ref: Reference, client: RetrievalClient, para_len: int
) -> tuple[RefCheck, Finding | None]:
    # 1. complete missing fields via LLM (structure task, cloud)
    if not (ref.title and ref.authors and ref.year):
        filled = await complete_reference_fields(ref.raw)
        ref.title = ref.title or filled.get("title")
        if not ref.authors and filled.get("authors"):
            ref.authors = filled["authors"]
        ref.year = ref.year or filled.get("year")
        ref.venue = ref.venue or filled.get("venue")
        ref.doi = ref.doi or filled.get("doi")

    # 2. gather candidate hits
    hits, responded, _ = await _gather_hits(ref, client)

    # 3. best hit: among title matches (>=92) prefer the one whose fields
    # agree — a 2025 paper can share the title with the 2017 original.
    want_title = ref.title or ref.raw[:120]

    def _title_matches(pool: list[dict]) -> list[tuple[float, dict, list[str]]]:
        out = []
        for h in pool:
            if not h.get("title"):
                continue
            score = fuzz.token_sort_ratio(_norm(want_title), _norm(h["title"]))
            if score >= _TITLE_MIN:
                out.append((score, h, _evaluate(ref, h)))
        out.sort(key=lambda t: (len(t[2]), -t[0]))
        return out

    doi_hit: dict | None = None
    for h in hits:
        if ref.doi and h.get("doi") and ref.doi.lower() == str(h["doi"]).lower():
            doi_hit = h
    title_matches = _title_matches(hits)

    # targeted pass: when the best title-matched record disagrees on the
    # first author or year, a same-titled different work may be hiding the
    # real record — search title + surname before concluding mismatch.
    if title_matches and any(
        "首作者" in i or "年份" in i for i in title_matches[0][2]
    ):
        extra = await _author_hits(ref, client)
        if extra:
            hits += extra
            retried = _title_matches(hits)
            if retried and len(retried[0][2]) < len(title_matches[0][2]):
                title_matches = retried

    issues: list[str] = []
    matched: dict | None = None
    if title_matches:
        title_matches.sort(key=lambda t: (len(t[2]), -t[0]))
        _score, matched, issues = title_matches[0]
        # fill abstract/pdf/arxiv from sibling records of the same work so
        # T3 gets the richest available source text; keep the rest as
        # fallback abstract candidates
        extras: list[str] = []
        for _s, h, _iss in title_matches[1:]:
            for k in ("abstract", "pdf_url", "arxiv_id", "alt_year"):
                if not matched.get(k) and h.get(k):
                    matched[k] = h[k]
            a = h.get("abstract")
            if a and a != matched.get("abstract") and a not in extras:
                extras.append(a)
        if extras:
            matched["extra_abstracts"] = extras
        if (
            ref.doi and matched.get("doi")
            and ref.doi.lower() != str(matched["doi"]).lower()
        ):
            issues.append(
                f"DOI 不一致：文中写 {ref.doi}，数据库记录为 {matched['doi']}"
            )
        status = "mismatch" if issues else "verified"
    elif doi_hit is not None:
        matched = doi_hit
        status = "mismatch"
        issues = [
            f"DOI 指向另一篇文献：文中写《{want_title[:60]}》，"
            f"该 DOI 实际为《{str(doi_hit.get('title'))[:60]}》"
        ]
    else:
        matched = None
        if len(responded) >= len(_SOURCES) and ref.lang == "en":
            status = "not_found"
            issues = ["三个数据库均未检索到相符文献"]
        else:
            status = "unverifiable"
            missing = [s for s in _SOURCES if s not in responded]
            issues = (
                ["检索服务暂不可用，未能完成核验"]
                if missing
                else ["未检索到相符记录，中文文献暂以无法核验处理"]
            )
        if ref.lang == "zh":
            status = "unverifiable" if status != "mismatch" else status

    check = RefCheck(ref_id=ref.id, status=status, matched=matched, issues=issues)
    finding = None if status == "verified" else _finding(ref, check, para_len)
    return check, finding


async def verify_references(
    references: list[Reference],
    paragraphs: list[Paragraph],
    client: RetrievalClient | None = None,
) -> tuple[list[RefCheck], list[Finding]]:
    para_len = {p.id: len(p.text) for p in paragraphs}
    own = client is None
    if own:
        client = RetrievalClient()
    try:
        results = await asyncio.gather(
            *[_verify_one(r, client, para_len.get(r.paragraph_id or "", 0))
              for r in references]
        )
    finally:
        if own:
            await client.close()
    checks: list[RefCheck] = []
    findings: list[Finding] = []
    for check, finding in results:
        checks.append(check)
        if finding is not None:
            finding.id = f"auth-{len(findings)}"
            findings.append(finding)
    return checks, findings
