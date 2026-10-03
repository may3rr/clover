"""真实性核验：每条参考文献是否真的存在、字段是否一致。

A title-matched record that disagrees on BOTH first author AND year is a
different work that happens to share the title — it is dropped from the
candidate pool entirely instead of producing a mismatch.

Verification runs in stages (T6 speed): Crossref/OpenAlex/S2 first for
every ref in parallel; refs not verified there go through batched arXiv
title lookups (≤5 titles per request) plus a per-ref loose fallback, and
finally the author-targeted pass. Refs that verify early never touch
arXiv. ``on_ref`` is called the moment each ref's RefCheck is final so the
pipeline can start that ref's support checks immediately.

Status semantics (PLAN T2):
- verified: title、首作者、年份都对上；
- mismatch: 某条标题匹配记录至少一个字段对得上但其余有出入，或显式
  DOI 解析到了别的文献；
- not_found: 英文文献，Crossref、OpenAlex、arXiv 都真正响应且都没有
  可用匹配（S2 是可选源：它若响应也必须无匹配——能走到这里本来就意
  味着没有任何源匹配上）；
- unverifiable: 中文文献查不到，或上述三个必需源之一不可用。

A source that errored/timed out is "unavailable", never "no hit".
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..parse.links import latin_surname
from ..schema import Anchor, Finding, Paragraph, RefCheck, Reference
from .sources import RetrievalClient, SourceResult
from .structure import complete_reference_fields

log = logging.getLogger(__name__)

_TITLE_MIN = 92.0
_SURNAME_MIN = 85.0
_SOURCES = ("crossref", "openalex", "s2", "arxiv")
# not_found (English refs) requires these three to have really answered;
# s2 is optional — rate-limited S2 must not block a fabricated ref from
# reaching not_found.
_REQUIRED = ("crossref", "openalex", "arxiv")
_SRC_LABEL = {
    "crossref": "Crossref",
    "openalex": "OpenAlex",
    "s2": "Semantic Scholar",
    "arxiv": "arXiv",
}
_ARXIV_BATCH = 5

_CJK = re.compile(r"[一-鿿]")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[^a-z0-9一-鿿]+", " ", s).strip()


def _surname(name: str) -> str:
    """Surname from 'Surname, I.' / 'Vaswani A' / 'Ashish Vaswani' / 中文名.

    """
    n = (name or "").strip()
    if not n:
        return ""
    zh = _CJK.search(n)
    if zh:
        return n[zh.start()]  # Chinese surname = first character
    # manuscript lists may be "Surname, I.", "Surname I" or ACL "Given
    # Surname"; database display names are "Given Surname" — the shared
    # heuristic reads all of them the same way
    return latin_surname(n)


def _ref_surname(ref: Reference) -> str:
    return _surname(ref.authors[0]) if ref.authors else ""


def _hit_surname(hit: dict) -> str:
    authors = hit.get("authors") or []
    return _surname(authors[0]) if authors else ""


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
    """Crossref + OpenAlex + S2 only — arXiv runs separately (batched) for
    refs these three don't verify."""
    query = ref.title or ref.raw[:200]
    calls = [
        client.crossref_search(query),
        client.openalex_search(query),
        client.s2_search(query),
    ]
    # a second, year-filtered pass: canonical records (e.g. the 2017
    # Transformer paper) can be pushed out of search results by later
    # same-titled works. arXiv has no year filter — the preprint may
    # predate the cited venue year anyway.
    if ref.year:
        calls += [
            client.crossref_search(query, year=ref.year),
            client.openalex_search(query, year=ref.year),
            client.s2_search(query, year=ref.year),
        ]
        srcs = _SOURCES[:3] * 2
    else:
        srcs = _SOURCES[:3]
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
        client.arxiv_search(ref.title, author=surname),
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


def _evaluate(
    ref: Reference, hit: dict
) -> tuple[list[str], bool, bool]:
    """Field-level issues for a title-matched hit; empty issues = verified.
    Returns (issues, author_differs, year_differs) — 'differs' is only
    True when both sides have the field and they disagree."""
    issues: list[str] = []
    author_diff = False
    year_diff = False
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
            a, b = _norm(ref_surname), _norm(hit_surname)
            # particles are written inconsistently ("van den Oord" / "Oord")
            ok = (fuzz.ratio(a, b) >= _SURNAME_MIN
                  or a.split()[-1:] == b.split()[-1:])
        if not ok:
            author_diff = True
            issues.append(
                f"首作者不一致：文中写 {ref.authors[0]}，数据库记录为 {hit['authors'][0]}"
            )
    if ref.year and hit.get("year"):
        # a reprint's record year can postdate the work; the arXiv version's
        # year (alt_year) is an acceptable match too. An arXiv preprint may
        # be up to 2 years EARLIER than the cited (venue) year.
        is_arxiv = hit.get("source") == "arxiv"
        years = [y for y in (hit["year"], hit.get("alt_year")) if y]
        if is_arxiv:
            ok = any(ref.year - 2 <= int(y) <= ref.year + 1 for y in years)
        else:
            ok = any(abs(int(y) - ref.year) <= 1 for y in years)
        if not ok:
            year_diff = True
            issues.append(
                f"年份不一致：文中写 {ref.year}，数据库记录为 {hit['year']}"
            )
    if ref.doi and hit.get("doi") and ref.doi.lower() != str(hit["doi"]).lower():
        issues.append(f"DOI 不一致：文中写 {ref.doi}，数据库记录为 {hit['doi']}")
    return issues, author_diff, year_diff


def _finding(ref: Reference, check: RefCheck, para_len: int) -> Finding:
    anchor = Anchor(paragraph_id=ref.paragraph_id or "", start=0, end=para_len)
    if check.status == "not_found":
        answered = "、".join(
            _SRC_LABEL[s] for s in _SOURCES if s in check.answered
        )
        return Finding(
            id="", layer="authenticity", severity="high", anchor=anchor,
            title="未能在数据库中找到这篇文献",
            detail=f"依据：{answered}均未检索到标题或作者相符的记录。\n"
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


@dataclass
class _State:
    """Per-ref candidate pool + which sources really answered."""
    hits: list[dict] = field(default_factory=list)
    responded: set[str] = field(default_factory=set)


def _select(
    ref: Reference, hits: list[dict]
) -> tuple[list[tuple[float, dict, list[str]]], dict | None]:
    """Title-matched candidates (sorted: fewest issues, then best score)
    + the record the explicit DOI resolves to, if any."""
    want_title = ref.title or ref.raw[:120]
    out: list[tuple[float, dict, list[str]]] = []
    doi_hit: dict | None = None
    for h in hits:
        if (
            ref.doi and h.get("doi")
            and ref.doi.lower() == str(h["doi"]).lower()
        ):
            doi_hit = h
        if not h.get("title"):
            continue
        score = fuzz.token_sort_ratio(_norm(want_title), _norm(h["title"]))
        if score < _TITLE_MIN:
            continue
        issues, author_diff, year_diff = _evaluate(ref, h)
        # A record disagreeing on BOTH first author and year is a
        # different work sharing the title — drop it from the pool.
        # A shared DOI overrides: same work, messy metadata.
        if author_diff and year_diff and h is not doi_hit:
            continue
        out.append((score, h, issues))
    out.sort(key=lambda t: (len(t[2]), -t[0]))
    return out, doi_hit


def _conclude(
    ref: Reference,
    title_matches: list[tuple[float, dict, list[str]]],
    doi_hit: dict | None,
    responded: set[str],
    para_len: int,
) -> tuple[RefCheck, Finding | None]:
    """Status assignment + optional authenticity finding."""
    want_title = ref.title or ref.raw[:120]
    issues: list[str] = []
    matched: dict | None = None
    if title_matches:
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
        if ref.lang == "en" and set(_REQUIRED) <= responded:
            status = "not_found"
            answered = "、".join(
                _SRC_LABEL[s] for s in _SOURCES if s in responded
            )
            issues = [f"{answered}均未检索到相符文献"]
        else:
            status = "unverifiable"
            missing = [s for s in _REQUIRED if s not in responded]
            issues = (
                ["检索服务暂不可用，未能完成核验"]
                if missing
                else ["未检索到相符记录，中文文献暂以无法核验处理"]
            )
        if ref.lang == "zh":
            status = "unverifiable" if status != "mismatch" else status

    check = RefCheck(ref_id=ref.id, status=status, matched=matched, issues=issues)
    check.answered = sorted(responded)
    finding = None if status == "verified" else _finding(ref, check, para_len)
    return check, finding


async def _finalize(
    ref: Reference, st: _State, client: RetrievalClient, para_len: int
) -> tuple[RefCheck, Finding | None]:
    """Refs the first three sources didn't verify: loose arXiv fallback,
    then the author-targeted pass, then conclude."""
    title_matches, doi_hit = _select(ref, st.hits)

    # loose AND-words arXiv query when the batch phrase found nothing
    if not title_matches and doi_hit is None and ref.title:
        r = await client.arxiv_loose_search(ref.title)
        if r.ok:
            st.responded.add("arxiv")
            if r.data:
                st.hits += r.data
                title_matches, doi_hit = _select(ref, st.hits)

    # targeted pass: when the best title-matched record disagrees on the
    # first author or year, a same-titled different work may be hiding the
    # real record — search title + surname before concluding mismatch.
    if title_matches and any(
        "首作者" in i or "年份" in i for i in title_matches[0][2]
    ):
        extra = await _author_hits(ref, client)
        if extra:
            st.hits += extra
            retried, doi_hit2 = _select(ref, st.hits)
            doi_hit = doi_hit or doi_hit2
            if retried and len(retried[0][2]) < len(title_matches[0][2]):
                title_matches = retried

    return _conclude(ref, title_matches, doi_hit, st.responded, para_len)


async def _stage1(
    ref: Reference, client: RetrievalClient
) -> _State:
    """Field completion + Crossref/OpenAlex/S2 (+DOI lookups)."""
    if not (ref.title and ref.authors and ref.year):
        filled = await complete_reference_fields(ref.raw)
        ref.title = ref.title or filled.get("title")
        if not ref.authors and filled.get("authors"):
            ref.authors = filled["authors"]
        ref.year = ref.year or filled.get("year")
        ref.venue = ref.venue or filled.get("venue")
        ref.doi = ref.doi or filled.get("doi")
    hits, responded, _ = await _gather_hits(ref, client)
    return _State(hits=hits, responded=responded)


async def verify_references(
    references: list[Reference],
    paragraphs: list[Paragraph],
    client: RetrievalClient | None = None,
    on_ref: Callable[[RefCheck], object] | None = None,
) -> tuple[list[RefCheck], list[Finding]]:
    """Verify all refs; ``on_ref(check)`` fires as each check is final —
    verified refs emit as soon as the first three sources agree, without
    waiting for arXiv batches for the stragglers."""
    para_len = {p.id: len(p.text) for p in paragraphs}
    own = client is None
    if own:
        client = RetrievalClient()
    checks: dict[str, RefCheck] = {}
    findings: dict[str, Finding] = {}
    states: dict[str, _State] = {}
    pending: list[Reference] = []

    async def _emit(ref: Reference, check: RefCheck, finding: Finding | None):
        checks[ref.id] = check
        if finding is not None:
            findings[ref.id] = finding
        if on_ref is not None:
            r = on_ref(check)
            if inspect.isawaitable(r):
                await r

    try:
        async def _s1(ref: Reference) -> None:
            st = await _stage1(ref, client)
            states[ref.id] = st
            title_matches, doi_hit = _select(ref, st.hits)
            # DOI resolving to a different work is conclusive — arXiv
            # can't un-mismatch it. Verified emits immediately too.
            conclusive = doi_hit is not None and not title_matches
            if (title_matches and not title_matches[0][2]) or conclusive:
                check, finding = _conclude(
                    ref, title_matches, doi_hit, st.responded,
                    para_len.get(ref.paragraph_id or "", 0))
                await _emit(ref, check, finding)
            else:
                pending.append(ref)

        await asyncio.gather(*(_s1(r) for r in references))

        # stage 2: batched arXiv phrase lookups for the pending refs
        for i in range(0, len(pending), _ARXIV_BATCH):
            chunk = pending[i : i + _ARXIV_BATCH]
            r = await client.arxiv_search_batch(
                [x.title or x.raw[:200] for x in chunk],
                max_results=5,  # single-title batch = arxiv_search key
            )
            if not r.ok:
                continue
            for ref in chunk:
                st = states[ref.id]
                st.responded.add("arxiv")
                want = _norm(ref.title or ref.raw[:120])
                for h in r.data or []:
                    if not h.get("title"):
                        continue
                    if fuzz.token_sort_ratio(want, _norm(h["title"])) >= _TITLE_MIN:
                        st.hits.append(h)

        # stage 3: per-ref finalize (loose fallback + author pass)
        async def _fin(ref: Reference) -> None:
            check, finding = await _finalize(
                ref, states[ref.id], client,
                para_len.get(ref.paragraph_id or "", 0))
            await _emit(ref, check, finding)

        await asyncio.gather(*(_fin(ref) for ref in pending))
    finally:
        if own:
            await client.close()

    out_checks: list[RefCheck] = []
    out_findings: list[Finding] = []
    for r in references:
        if r.id in checks:
            out_checks.append(checks[r.id])
        if r.id in findings:
            out_findings.append(findings[r.id])
    for i, f in enumerate(out_findings):
        f.id = f"auth-{i}"
    return out_checks, out_findings
