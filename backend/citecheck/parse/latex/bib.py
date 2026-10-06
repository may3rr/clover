"""最小 BibTeX 解析器：@entry{key, field = value}。

支持 {..} / ".." / 裸词三种值写法、# 拼接、@string 定义；@preamble /
@comment 跳过。不引入外部依赖，够用即可——bib 条目格式远比 docx
自由文本规整，正则 + 配对括号扫描可以覆盖绝大多数情况。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...refs.structure import detect_lang
from .tex import _read_balanced, render


@dataclass
class BibEntry:
    key: str
    type: str
    fields: dict[str, str] = field(default_factory=dict)


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\n":
        i += 1
    return i


def _read_quoted(s: str, i: int) -> tuple[str, int] | None:
    """s[i] == '"' → (value, next)。引号内的 {} 按字面处理。"""
    j = i + 1
    out = []
    while j < len(s):
        c = s[j]
        if c == "\\" and j + 1 < len(s):
            out.append(s[j : j + 2])
            j += 2
            continue
        if c == '"':
            return "".join(out), j + 1
        if c == "{":
            r = _read_balanced(s, j, "{", "}")
            if r is None:
                break
            out.append(s[j : r[1]])
            j = r[1]
            continue
        out.append(c)
        j += 1
    return None


def _read_bare(s: str, i: int) -> tuple[str, int]:
    m = re.match(r"[^,#\s}]+", s[i:])
    if not m:
        return "", i
    return m.group(0), i + m.end()


def _parse_fields(s: str, strings: dict[str, str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    i = 0
    while True:
        i = _skip_ws(s, i)
        if i < len(s) and s[i] == "%":  # 字段边界上的 % 是注释
            j = s.find("\n", i)
            i = len(s) if j < 0 else j + 1
            continue
        if i < len(s) and s[i] == ",":
            i += 1
            continue
        m = re.match(r"([a-zA-Z_:][\w:.-]*)\s*=", s[i:])
        if not m:
            break
        name = m.group(1).lower()
        i += m.end()
        parts: list[str] = []
        while True:
            i = _skip_ws(s, i)
            if i >= len(s):
                break
            if s[i] == "{":
                r = _read_balanced(s, i, "{", "}")
                if r is None:
                    i = len(s)
                    break
                parts.append(r[0])
                i = r[1]
            elif s[i] == '"':
                r = _read_quoted(s, i)
                if r is None:
                    i = len(s)
                    break
                parts.append(r[0])
                i = r[1]
            else:
                v, i = _read_bare(s, i)
                parts.append(strings.get(v, v))
            i = _skip_ws(s, i)
            if i < len(s) and s[i] == "#":
                i += 1
                continue
            break
        fields[name] = "".join(parts)
    return fields


def parse_bib(text: str) -> list[BibEntry]:
    """解析 .bib 全文，按文件顺序返回条目。"""
    entries: list[BibEntry] = []
    strings: dict[str, str] = {}
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "%":  # 条目外的 % 视为注释
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c != "@":
            i += 1
            continue
        m = re.match(r"@\s*([a-zA-Z]+)\s*([({])", text[i:])
        if not m:
            i += 1
            continue
        etype = m.group(1).lower()
        open_i = i + m.end() - 1
        open_c, close_c = ("(", ")") if m.group(2) == "(" else ("{", "}")
        r = _read_balanced(text, open_i, open_c, close_c)
        if r is None:
            break
        body, i = r
        if etype in {"preamble", "comment"}:
            continue
        if etype == "string":
            for k, v in _parse_fields(body, strings).items():
                strings[k] = v
            continue
        comma = body.find(",")
        if comma < 0:
            continue
        key = body[:comma].strip()
        if not key:
            continue
        entries.append(BibEntry(key, etype, _parse_fields(body[comma + 1 :], strings)))
    return entries


_VENUE_FIELDS = ("journal", "journaltitle", "booktitle", "series",
                 "publisher", "school", "institution", "howpublished")


def clean_field(value: str) -> str:
    """bib 字段值 → 纯文本（去分组括号、转换命令与变音符）。"""
    t, _ = render(value, None)
    return t.strip()


def entry_fields(e: BibEntry) -> dict:
    """BibEntry → Reference 需要的结构化字段。"""
    f = e.fields
    authors = [
        clean_field(a)
        for a in re.split(r"\s+and\s+", f.get("author", ""))
        if a.strip()
    ]
    title = clean_field(f.get("title", "")) or None
    year = None
    for cand in (f.get("year", ""), f.get("date", "")):
        m = re.search(r"(?:19|20)\d{2}", cand)
        if m:
            year = int(m.group(0))
            break
    venue = next((clean_field(f[k]) for k in _VENUE_FIELDS if f.get(k)), None)
    if not venue and f.get("eprint") and "arxiv" in f.get("archiveprefix", "").lower():
        venue = f"arXiv:{clean_field(f['eprint'])}"
    doi = clean_field(f.get("doi", "")) or None
    raw = _format_raw(e, authors, title, year, venue, doi)
    return {
        "label": None,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "doi": doi,
        "lang": detect_lang(raw),
        "raw": raw,
    }


def _format_raw(e: BibEntry, authors: list[str], title: str | None,
                year: int | None, venue: str | None, doi: str | None) -> str:
    """把 bib 条目格式化成一条参考文献文本（报告页展示 + norms/重复
    检测用 raw 文本）。"""
    parts = []
    if authors:
        a = ", ".join(authors)
        parts.append(a if a.endswith(".") else a + ".")
    if title:
        parts.append(title if title.endswith(".") else title + ".")
    tail = ", ".join(v for v in (venue, str(year) if year else None) if v)
    if tail:
        parts.append(tail + ".")
    if doi:
        parts.append(f"doi:{doi}")
    return " ".join(parts) or f"@{e.type}{{{e.key}}}"
