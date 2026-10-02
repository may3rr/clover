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

_EN_NAME = re.compile(r"^[A-Z][A-Za-z'’\-]*(?:\s+[A-Z]\.?)*$")
_EN_INITIAL = re.compile(r"^[A-Z](?:\.-?[A-Z]\.?)*\.?$")
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


def _looks_like_author_list(chunk: str) -> bool:
    c = chunk.strip()
    if not c or len(c) > 250:
        return False
    if re.search(r"et\s+al|等", c):
        return True
    parts = re.split(r"[,，、;；]\s*|\s+and\s+|\s*&\s*", c)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return False
    hit = 0
    for p in parts:
        if _EN_NAME.match(p) or _ZH_NAME.match(p) or _EN_INITIAL.match(p):
            hit += 1
    return hit >= max(1, len(parts) - 1)


def _split_en_apa_authors(part: str) -> list[str]:
    """'Devlin, J., Chang, M.-W., & Lee, K.' -> ['Devlin, J.', ...]."""
    tokens = [t.strip() for t in re.split(r"\s*,\s*|\s+and\s+|\s*&\s*", part) if t.strip()]
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

    # "(2017)." APA-style year immediately after authors
    apa = re.search(r"\(((?:19|20)\d{2})[a-z]?\)\s*\.?\s*", body)
    year_m = apa or _YEAR_RE.search(body)
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
    if chunks and _looks_like_author_list(chunks[0]) and len(chunks) > 1:
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
