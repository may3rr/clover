"""Link detected markers to reference-list entries.

- numeric / superscript: expand numbers and ranges, resolve by the
  entry's visible label, falling back to list position — POSITION means
  position among ``origin == "list"`` entries only (footnote-promoted
  references never occupy the numbered list);
- author_year: match (first-author surname, year) with rapidfuzz, using
  the a/b suffix to disambiguate same-author-same-year entries;
- zotero / endnote: match the field's structured item data (title, then
  author+year) against the entries;
- footnote markers are NOT resolved here — the parser links them by
  note id (they know exactly which note body they point at).
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from ..schema import Reference
from .markers import DetectedMarker

_NUM_TOKEN = re.compile(r"\d+\s*[-–—~～]\s*\d+|\d+")
_ZH_NAME = re.compile(r"[一-鿿]{2,4}")
_YEAR = re.compile(r"((?:19|20)\d{2})([a-z])?")


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip().lower()


def _numeric_items(raw: str) -> list[int]:
    """'[1,3]' -> [1, 3]; '[2-5]' / '2–5' -> [2, 3, 4, 5]."""
    nums: list[int] = []
    for tok in _NUM_TOKEN.findall(raw):
        m = re.match(r"(\d+)\s*[-–—~～]\s*(\d+)", tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            nums.extend(range(a, b + 1) if a <= b else range(b, a + 1))
        else:
            nums.append(int(tok))
    return nums


_PARTICLES = {"van", "von", "de", "der", "den", "del", "della", "di", "da",
              "du", "la", "le", "ter", "ten", "dos", "das", "al", "bin"}


def _ref_first_surname(ref: Reference) -> str:
    if not ref.authors:
        return ""
    first = ref.authors[0].strip()
    if _ZH_NAME.search(first):
        return _ZH_NAME.search(first).group(0)  # type: ignore[union-attr]
    if "," in first:  # "Devlin, J."
        return first.split(",", 1)[0].strip()
    toks = first.split()
    if len(toks) == 1:
        return toks[0]
    # "Devlin J" / "Devlin JM" / "Devlin J. M." — surname first, initials after
    if all(re.fullmatch(r"(?:[A-Z]\.?-?){1,3}", t) for t in toks[1:]):
        return toks[0]
    # "Jacob Devlin" / "Aaron van den Oord" (ACL full names) — surname last,
    # keeping lowercase particles that belong to it
    i = len(toks) - 1
    while i > 1 and toks[i - 1].lower() in _PARTICLES:
        i -= 1
    return " ".join(toks[i:])


def _marker_surname(authors_part: str) -> str:
    """First-author name out of 'Smith et al.' / 'Smith & Lee' / '张三等'."""
    a = re.split(r"\s+et\s+al\.?|\s+and\s+|\s*&\s*|等|和", authors_part.strip())[0]
    return a.strip(" ,，、.。")


def author_year_items(raw: str) -> list[tuple[str, str, str | None]]:
    """Extract (authors_part, year, suffix) triples from a marker's raw text."""
    items: list[tuple[str, str, str | None]] = []
    body = raw.strip()
    outer = re.fullmatch(r"[\(（](.*)[\)）]", body, re.S)
    if outer:
        for part in re.split(r"[;；]", outer.group(1)):
            ym = _YEAR.search(part)
            if not ym:
                continue
            authors_part = part[: ym.start()].strip(" ,，、　")
            if authors_part:
                items.append((authors_part, ym.group(1), ym.group(2)))
    else:
        ym = _YEAR.search(body)
        if ym:
            # narrative 'Name (2020)': author text sits before the bracket
            authors_part = re.split(r"[\(（]", body[: ym.start()])[0]
            authors_part = authors_part.strip(" ,，、　")
            if authors_part:
                items.append((authors_part, ym.group(1), ym.group(2)))
    return items


def _number_resolver(references: list[Reference]):
    ordered = [r for r in references if r.origin == "list"]
    by_label = {r.label: r for r in ordered if r.label}

    def resolve_number(n: int) -> str | None:
        ref = by_label.get(str(n))
        if ref is not None:
            return ref.id
        if 1 <= n <= len(ordered):
            return ordered[n - 1].id
        return None

    return resolve_number


def unresolved_numeric(raw: str, references: list[Reference]) -> list[int]:
    """Numbers in a marker's raw text that match no reference entry."""
    resolve = _number_resolver(references)
    return [n for n in _numeric_items(raw) if resolve(n) is None]


def link_markers(
    markers: list[DetectedMarker], references: list[Reference]
) -> list[list[str]]:
    """Return ref_id lists parallel to ``markers``."""
    ordered = list(references)  # author-year / field matching: all entries
    surnames = [_norm(_ref_first_surname(r)) for r in ordered]
    resolve_number = _number_resolver(references)

    def resolve_author_year(authors_part: str, year: str, suffix: str | None) -> str | None:
        want = _norm(_marker_surname(authors_part))
        if not want:
            return None
        scored = []
        for i, r in enumerate(ordered):
            if r.year is not None and r.year != int(year):
                continue
            if not surnames[i]:
                continue
            if _ZH_NAME.fullmatch(want):
                score = (
                    100.0
                    if surnames[i] == want
                    or surnames[i].startswith(want)
                    or _norm(r.authors[0]) == want
                    else 0.0
                )
            else:
                score = fuzz.ratio(want, surnames[i])
            if score >= 85:
                scored.append((score, i))
        if not scored:
            return None
        scored.sort(key=lambda t: (-t[0], t[1]))
        best = [i for s, i in scored if s == scored[0][0]]
        if suffix and len(best) > 1:
            k = ord(suffix) - ord("a")
            if 0 <= k < len(best):
                return ordered[best[k]].id
        return ordered[best[0]].id

    def resolve_zotero_item(item: dict) -> str | None:
        title = item.get("title") or ""
        year = None
        try:
            year = item.get("issued", {}).get("date-parts", [[None]])[0][0]
        except (AttributeError, IndexError, TypeError):
            year = None
        fams = [
            _norm(a.get("family", ""))
            for a in item.get("author", []) or []
            if isinstance(a, dict)
        ]
        best: tuple[float, int] | None = None
        for i, r in enumerate(ordered):
            score = 0.0
            if title and r.title:
                score = fuzz.token_sort_ratio(_norm(title), _norm(r.title))
            elif title:
                score = fuzz.partial_ratio(_norm(title), _norm(r.raw)) * 0.9
            if year and r.year == int(year):
                score += 10
            if fams and surnames[i] and surnames[i] == fams[0]:
                score += 10
            if best is None or score > best[0]:
                best = (score, i)
        if best and best[0] >= 80:
            return ordered[best[1]].id
        return None

    results: list[list[str]] = []
    for mk in markers:
        ids: list[str] = []
        if mk.kind in {"numeric", "superscript"}:
            for n in _numeric_items(mk.raw):
                rid = resolve_number(n)
                if rid and rid not in ids:
                    ids.append(rid)
        elif mk.kind == "author_year":
            for authors_part, year, suffix in author_year_items(mk.raw):
                rid = resolve_author_year(authors_part, year, suffix)
                if rid and rid not in ids:
                    ids.append(rid)
        elif mk.kind == "zotero" and mk.items:
            for item in mk.items:
                rid = resolve_zotero_item(item)
                if rid and rid not in ids:
                    ids.append(rid)
        elif mk.kind == "endnote":
            for n in _numeric_items(mk.raw):
                rid = resolve_number(n)
                if rid and rid not in ids:
                    ids.append(rid)
            if not ids:
                for authors_part, year, suffix in author_year_items(mk.raw):
                    rid = resolve_author_year(authors_part, year, suffix)
                    if rid and rid not in ids:
                        ids.append(rid)
        results.append(ids)
    return results
