"""Light regex/heuristic extraction of Reference fields from a raw entry.

This is the fast path; T2 extends it (LLM completion for entries that
stay partially blank). Everything here is best-effort — fields it cannot
extract are left None rather than guessed.
"""

from __future__ import annotations

import re
from typing import Any

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>，。；]+")
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})[a-z]?(?!\d)")
_LABEL_RE = re.compile(r"^\s*[\[\(（【]?(\d{1,3})[\]\)）】]?[\.、]?\s+")
_CJK_RE = re.compile(r"[一-鿿]")
_TYPE_TAG_RE = re.compile(r"\[[JMDPCRNSZOA](/[A-Z]{1,2})?\]")

# ACL / EMNLP: "Given Surname, Given Surname, and Given Surname. 2020.
# Title. In Venue, pages 1–9." — the year is its own sentence after the
# author list. Non-greedy authors stop at the first ". YYYY." so middle
# initials ("Aidan N. Gomez") never end the author list early.
_ACL_RE = re.compile(r"^(?P<authors>.+?)\.\s+(?P<year>(?:19|20)\d{2})[a-z]?\.\s+(?P<rest>.+)$", re.S)
# a year that names an event rather than dating the work:
# "Proceedings of the 2022 Conference on ...", "2021 Annual Meeting"
_EVENT_YEAR_RE = re.compile(
    r"\s+(Conference|Annual|Meeting|Workshop|International|Joint|Findings|Edition)\b")

_EN_NAME = re.compile(r"^[^\W\d_][^\W\d_'’\-]*(?:\s+[^\W\d_]\.?)*$")
_EN_INITIAL = re.compile(r"^[^\W\d_](?:\.-?\s?[^\W\d_]\.?)*\.?$")
_ZH_NAME = re.compile(r"^[一-鿿]{2,4}$")


def extract_label(raw: str) -> str | None:
    m = _LABEL_RE.match(raw)
    return m.group(1) if m else None


def detect_lang(raw: str) -> str:
    cjk = len(_CJK_RE.findall(raw))
    if cjk >= 2:
        return "zh"
    asciiish = sum(1 for c in raw if ord(c) < 128)
    return "en" if raw and asciiish / len(raw) > 0.9 else "other"


_NAME_PARTICLES = {"van", "von", "de", "der", "den", "del", "della", "di",
                   "da", "du", "la", "le", "ter", "ten", "dos", "das", "al", "bin"}


def _is_full_name(p: str) -> bool:
    """'Akari Asai', 'Emily M. Bender', 'Aaron van den Oord' — given name(s)
    then surname. Only trusted where the entry's shape already says
    "author list" (the ACL year sentence), since Title-Case titles look
    the same."""
    toks = p.split()
    if not 2 <= len(toks) <= 5:
        return False
    return all(t[0].isupper() or t.lower() in _NAME_PARTICLES for t in toks) \
        and toks[-1][0].isupper()


def _looks_like_author_list(chunk: str, full_names: bool = False) -> bool:
    c = chunk.strip()
    if not c or len(c) > 600:
        return False
    if re.search(r"et\s+al|等", c):
        return True
    parts = re.split(r"[,，、;；]\s*(?:&\s*)?|\s+and\s+|\s*&\s*", c)
    parts = [re.sub(r"^and\s+", "", p.strip()) for p in parts if p.strip()]
    if not parts:
        return False
    hit = 0
    for p in parts:
        if (_EN_NAME.match(p) or _ZH_NAME.match(p) or _EN_INITIAL.match(p)
                or (full_names and _is_full_name(p))):
            hit += 1
    return hit >= max(1, len(parts) - 1)


def _split_en_apa_authors(part: str) -> list[str]:
    """'Devlin, J., Chang, M.-W., & Lee, K.' -> ['Devlin, J.', ...]."""
    tokens = [t.strip() for t in re.split(r"\s*,\s*(?:&\s*)?|\s+and\s+|\s*&\s*", part) if t.strip()]
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if _EN_NAME.match(t) and not _EN_INITIAL.match(t):
            initials = []
            j = i + 1
            while j < len(tokens) and _EN_INITIAL.match(tokens[j]):
                initials.append(tokens[j])
                j += 1
            out.append(t + (", " + " ".join(initials) if initials else ""))
            i = j
        else:
            out.append(t)
            i += 1
    return out


def parse_authors(part: str, lang: str) -> list[str]:
    c = re.sub(r"\s+", " ", part.strip().rstrip("."))
    if not c:
        return []
    if lang == "zh":
        raw = re.split(r"[,，、;；]\s*|\s+和\s*", c)
        return [a.strip() for a in raw if a.strip() and a.strip() != "等"]
    raw = re.split(r"\s+et\s+al\.?\s*", c)[0]
    if re.search(r"[A-Z][a-z]+,\s*[A-Z]\.?", raw):  # "Surname, I." style
        authors = _split_en_apa_authors(raw)
    else:
        authors = [
            a.strip()
            for a in re.split(r"\s*,\s*|\s+and\s+|\s*&\s*", raw)
            if a.strip()
        ]
    authors = [re.sub(r"^and\s+", "", a) for a in authors]
    return [a for a in authors if a and a.lower() not in {"et", "al", "et al."}]


def parse_reference(raw: str) -> dict:
    """Best-effort field extraction. Returns a dict with keys:
    label, title, authors, year, venue, doi, lang."""
    out: dict = {"label": None, "title": None, "authors": [], "year": None,
                 "venue": None, "doi": None, "lang": "other"}
    body = raw.strip()
    m = _LABEL_RE.match(body)
    if m:
        out["label"] = m.group(1)
        body = body[m.end():]

    doi = _DOI_RE.search(body)
    if doi:
        out["doi"] = doi.group(0).rstrip(".,;)")

    out["lang"] = detect_lang(body)

    acl = _ACL_RE.match(body)
    if acl and out["lang"] != "zh" and _looks_like_author_list(
            acl["authors"], full_names=True):
        out["year"] = int(acl["year"])
        out["authors"] = parse_authors(acl["authors"], out["lang"])
        # the title ends at its own sentence end — "?" and "!" stay in it
        title, venue = (re.split(r"(?<=[.?!])\s+", acl["rest"], maxsplit=1) + [""])[:2]
        out["title"] = title.rstrip(".").strip() or None
        venue = re.sub(r"^In\s+", "", venue.strip())
        venue = re.split(r",\s*(?:pages|pp\.|volume|vol\.)\b", venue)[0]
        out["venue"] = venue.strip(" .,") or None
        return out

    # "(2017)." APA-style year immediately after authors
    apa = re.search(r"\(((?:19|20)\d{2})[a-z]?\)\s*\.?\s*", body)
    # DOIs and URLs carry years too ("…/2022.emnlp-main.566") — blank them
    # out (same length, so offsets stay valid) before looking for the year
    dated = re.sub(r"https?://\S+|10\.\d{4,9}/\S+",
                   lambda m: " " * len(m.group(0)), body)
    year_m = apa or next(
        (m for m in _YEAR_RE.finditer(dated)
         if not _EVENT_YEAR_RE.match(dated, m.end())), None)
    if year_m:
        out["year"] = int(year_m.group(1))

    if apa:
        authors_part = body[: apa.start()]
        rest = body[apa.end():]
        title_m = re.split(r"\.\s+", rest, maxsplit=1)
        out["title"] = _TYPE_TAG_RE.sub("", title_m[0]).strip() or None
        if _looks_like_author_list(authors_part):
            out["authors"] = parse_authors(authors_part, out["lang"])
        return out

    chunks = re.split(r"\.\s+", body)
    idx = 0
    # three or more "Given Surname" names separated by commas is an author
    # list even without a year sentence (an ACL entry missing its year)
    if chunks and len(chunks) > 1 and _looks_like_author_list(
            chunks[0], full_names=chunks[0].count(",") >= 2):
        out["authors"] = parse_authors(chunks[0], out["lang"])
        idx = 1
    if idx < len(chunks):
        out["title"] = _TYPE_TAG_RE.sub("", chunks[idx]).strip(" .") or None
    # venue: the next chunk that isn't a bare year/pages/edition fragment
    for j in range(idx + 1, len(chunks)):
        venue = re.split(r"[,，]", chunks[j])[0]
        venue = _TYPE_TAG_RE.sub("", venue).strip()
        if not venue or re.fullmatch(r"[\d\s:()\-–—,，./]+", venue):
            continue
        if re.fullmatch(r"\d+(版|st|nd|rd|th)\.?", venue):
            continue
        out["venue"] = venue
        break
    return out


# ------------------------------------------------------------------ LLM

_PROMPT = (
    "把下面这条参考文献解析为 JSON。字段：title（论文标题，去掉[J][M]等类型标识）、"
    "authors（作者列表，英文保留原写法，中文每人一个字符串）、year（发表年份，整数）、"
    "venue（期刊或会议名）、doi。提取不出的字段用 null。只输出 JSON。\n\n"
    "参考文献：{raw}"
)


async def complete_reference_fields(raw: str) -> dict[str, Any]:
    """LLM fallback (task 'structure', cloud) for entries the regexes left
    incomplete. Returns a partial dict; empty on failure."""
    from pydantic import BaseModel

    from ..llm.client import chat_json

    class RefCompletion(BaseModel):
        title: str | None = None
        authors: list[str] = []
        year: int | None = None
        venue: str | None = None
        doi: str | None = None

    res = await chat_json(
        "structure",
        [{"role": "user", "content": _PROMPT.format(raw=raw)}],
        RefCompletion,
    )
    if res.value is None:
        return {}
    return {k: v for k, v in res.value.model_dump().items() if v}


# ------------------------------------------------------- LLM-first batch
#
# The regex path above is fast but can be confidently wrong (an ACL author
# list read as a title); the per-entry fallback only fires on blank fields.
# So every bibliography goes through the cheap model, ten entries a call,
# and the model's fields replace the regex ones — but only fields that can
# be found in the entry itself, so the model can restructure, never invent.

_BATCH = 10

_BATCH_PROMPT = (
    "下面是一篇论文参考文献列表中的若干条目，每条前有编号。逐条解析为 JSON。\n"
    "字段：i（条目编号）、title（论文或书的标题，不含作者、年份、会议名，去掉[J][M]等类型标识）、"
    "authors（作者列表，按原文顺序，英文保留原写法如 \"Patrick Lewis\" 或 \"Lewis, P.\"，"
    "中文每人一个字符串，不要包含 et al. 或“等”）、year（发表年份，整数；"
    "只取表示这篇文献发表时间的年份，会议名里的年份如“2022 Conference”不算，"
    "DOI 和网址里的年份也不算；没有就填 null）、venue（期刊或会议名）、doi。\n"
    "原文没有的信息一律填 null，不要补全、不要猜。\n"
    "只输出 JSON：{{\"items\": [{{\"i\": 1, \"title\": ..., \"authors\": [...], "
    "\"year\": ..., \"venue\": ..., \"doi\": ...}}]}}\n\n{entries}"
)


def _squash(s: str) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", (s or "").lower())


def _grounded(field: str, value: Any, raw: str) -> bool:
    """A model-proposed field is kept only if the entry itself contains it."""
    if value in (None, "", []):
        return False
    flat = _squash(raw)
    if field == "year":
        return bool(re.search(rf"(?<!\d){int(value)}(?!\d)", raw))
    if field == "doi":
        return str(value).lower() in raw.lower()
    if field == "authors":
        from ..parse.links import latin_surname

        first = str(value[0])
        key = first if _CJK_RE.search(first) else latin_surname(first)
        return bool(_squash(key)) and _squash(key) in flat
    # title / venue: near-verbatim (punctuation and case aside)
    from rapidfuzz import fuzz

    v = _squash(str(value))
    return bool(v) and (v in flat or fuzz.partial_ratio(v, flat) >= 95)


async def structure_references(refs: list) -> int:
    """Re-structure every reference with the model (batched, cached via
    chat_json). Returns how many references had authors or year changed —
    the caller relinks citation markers when that is non-zero."""
    import asyncio

    from pydantic import BaseModel

    from ..llm.client import chat_json

    class _Item(BaseModel):
        i: int
        title: str | None = None
        authors: list[str] = []
        year: int | None = None
        venue: str | None = None
        doi: str | None = None

    class _Batch(BaseModel):
        items: list[_Item] = []

    async def one(chunk: list) -> int:
        entries = "\n".join(f"[{k + 1}] {r.raw}" for k, r in enumerate(chunk))
        res = await chat_json(
            "structure",
            [{"role": "user", "content": _BATCH_PROMPT.format(entries=entries)}],
            _Batch,
        )
        if res.value is None:
            return 0
        changed = 0
        for it in res.value.items:
            if not 1 <= it.i <= len(chunk):
                continue
            r = chunk[it.i - 1]
            before = (tuple(r.authors), r.year)
            for field in ("title", "venue", "doi", "authors", "year"):
                val = getattr(it, field)
                if _grounded(field, val, r.raw):
                    setattr(r, field, val)
            if (tuple(r.authors), r.year) != before:
                changed += 1
        return changed

    chunks = [refs[i:i + _BATCH] for i in range(0, len(refs), _BATCH)]
    return sum(await asyncio.gather(*(one(c) for c in chunks)))
