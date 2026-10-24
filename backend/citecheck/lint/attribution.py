"""归属一致性（确定性规则，不调用模型）。

正文句里的作者归属写法——"徐增林等人[5]"、"Vaswani et al.[6]"、"Li等[7]"
——与被引文献的第一作者对不上，是张冠李戴（引用编号错位）的零证据信号：
不需要拿到被引文献的原文就能报警。

只在归属词紧邻单个数字引用标记、且该句只含这一个标记时判定；中文归属
只认"等人"（"…数据等[5]"里的"等"不是归属），拉丁名后的"等"可以。跨
文种（中文名对英文作者、拼音对中文作者）不判。实质性判断 → 只出批注，
永不生成修订。
"""

from __future__ import annotations

import re
import unicodedata

from ..schema import Anchor, Finding
from ..support.claims import split_sentences

# name immediately before 等人/等/et al., anchored at the marker
_ATTR_ZH_RE = re.compile(r"(?P<name>[\u4e00-\u9fff]{2,4})等人\s*$")
_ATTR_RE = re.compile(
    r"(?P<name>[A-Za-zÀ-ž][A-Za-zÀ-ž'\-\. ]{0,28}?)"
    r"(?:等人|等|et\s+al\.?)\s*$", re.I)

# collective nouns that read like "X等人" but are not people
_NOT_NAMES = {"学者", "方法", "模型", "技术", "数据", "工作", "作者",
              "用户", "系统", "算法", "指标", "任务", "工具", "专家"}

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def _family(author: str) -> tuple[str, str] | None:
    """(script, key) of a reference author string's family name."""
    a = (author or "").strip()
    if not a:
        return None
    if _CJK.search(a):
        return ("zh", a[0])
    fam = re.split(r"[\s.]+", _fold(a))[0]
    return ("latin", fam) if fam else None


def _attributed_name(window: str) -> tuple[str, int] | None:
    """(name, name_start_in_window) when the window ends with an
    attribution phrase hugging the marker."""
    m = _ATTR_ZH_RE.search(window)
    if m and not any(m.group("name").endswith(w) for w in _NOT_NAMES):
        return m.group("name"), m.start("name")
    m = _ATTR_RE.search(window)
    if m:
        name = m.group("name").strip(" .,-")
        # "Bordes和Weston等人" — the captured name is the second author of
        # the group; the first author may well be the ref's
        if m.start("name") > 0 and window[m.start("name") - 1] in "和与及、,，":
            return None
        if len(name) >= 2:
            return name, m.start("name")
    return None


def check_attribution(parsed) -> list[Finding]:
    """Medium support findings for in-text author attributions that
    contradict the cited reference's first author."""
    findings: list[Finding] = []
    para = {p.id: p for p in parsed.paragraphs}
    first_author: dict[str, tuple[str, str]] = {}
    for ref in parsed.references:
        fam = _family(ref.authors[0]) if ref.authors else None
        if fam is not None:
            first_author[ref.id] = fam

    by_para: dict[str, list] = {}
    all_by_para: dict[str, list] = {}
    for mk in parsed.markers:
        if not mk.ref_ids:
            continue
        all_by_para.setdefault(mk.paragraph_id, []).append(mk)
        if len(mk.ref_ids) == 1:
            by_para.setdefault(mk.paragraph_id, []).append(mk)

    for pid, marks in by_para.items():
        p = para.get(pid)
        if p is None or p.cell is not None:
            continue
        text = p.text
        sentences = split_sentences(text)
        every = all_by_para.get(pid, [])
        for mk in marks:
            alone = any(
                s.start <= mk.start < s.end
                and sum(1 for o in every if s.start <= o.start < s.end) == 1
                for s in sentences)
            if not alone:
                continue
            fam = first_author.get(mk.ref_ids[0])
            if fam is None:
                continue
            window = text[max(0, mk.start - 32):mk.start]
            hit = _attributed_name(window)
            if hit is None:
                continue
            name, wstart = hit
            if _CJK.search(name):
                nscript, nkey = "zh", name[0]
            else:
                nscript, nkey = "latin", _fold(re.split(r"[\s.]+", name)[0])
            if nscript != fam[0] or nkey == fam[1]:
                continue  # cross-script ambiguity, or names agree
            ref = next(
                (r for r in parsed.references if r.id == mk.ref_ids[0]), None)
            findings.append(Finding(
                id="", layer="support", severity="medium",
                anchor=Anchor(
                    paragraph_id=pid,
                    start=max(0, mk.start - 32) + wstart, end=mk.end),
                title="正文作者归属与文献作者不一致，可能引错了文献",
                detail=f"依据：正文写作“{name}等”，而被引文献的第一作者是"
                       f"“{(ref.authors[0] if ref and ref.authors else '？')}”，"
                       "两者对不上。\n"
                       "建议：确认这里想引用的是否是另一篇文献（引用编号"
                       "错位是常见原因）。",
                refs=[mk.ref_ids[0]],
            ))
    for i, f in enumerate(findings):
        f.id = f"attr-{i}"
    return findings
