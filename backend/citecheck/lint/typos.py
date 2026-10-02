"""错别字检查：每个正文段落一次 `typo` 任务调用。

只收集笔误：错别字、明显拼写错误、叠字（如"的的"）。不允许模型改
语法、措辞、风格、术语、专名、引用标记、数字或公式。

返回项校验与最小化：
- original 必须在段落中恰好出现一次（逐字），否则丢弃；
- correction 与 original 相同、改动了数字、或覆盖引用标记区间 → 丢弃；
- 去掉公共前后缀得到最小编辑区间；拉丁单词扩展到整个词边界；
- 最小编辑距离 > 2 → 不生成修订，给一条低优先级 finding
  "疑似笔误，请确认"，detail 中给出建议文本；
- 否则生成 Revision(kind="typo")。
"""

from __future__ import annotations

import asyncio
import re
import unicodedata

from pydantic import BaseModel, Field
from rapidfuzz.distance import Levenshtein

from ..llm.client import chat_json
from ..parse.parser import ParsedDocument
from ..schema import Anchor, Finding, Paragraph, Revision

_MATHY = re.compile(r"[0-9=+\-*/^(){}\[\]<>_\\]")
_LATIN_WORD = re.compile(r"[A-Za-z0-9]")
_MIN_LEN = 10

_PROMPT = """\
请找出下面段落中的笔误：错别字、明显拼写错误、重复出现的字（如"的的"）。
只报告笔误。不要修改语法、措辞、风格、术语、专有名词、引用标记
（如 [1]、(Author, 2020)）、数字或公式。
每一项的 original 必须是原文中恰好出现一次的字面片段，可以带上少量
上下文以保证唯一；correction 是对应的正确写法。
以 JSON 输出：{"items": [{"original": "...", "correction": "...",
"reason": "..."}]}；没有笔误时输出 {"items": []}。

段落：
{text}
"""


class _TypoItem(BaseModel):
    original: str = ""
    correction: str = ""
    reason: str = ""


class _TypoOut(BaseModel):
    items: list[_TypoItem] = Field(default_factory=list)


def _skippable(text: str) -> bool:
    t = text.strip()
    if len(t) < _MIN_LEN:
        return True
    return len(_MATHY.findall(t)) / max(len(t), 1) > 0.35


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _minimise(
    original: str, correction: str
) -> tuple[str, str, int, int]:
    """Trim the shared prefix/suffix; expand Latin mid-word cuts to whole
    words. Returns (old, new, rel_start, rel_end) in original coords."""
    i = 0
    while (
        i < len(original) and i < len(correction)
        and original[i] == correction[i]
    ):
        i += 1
    j = 0
    while (
        j < len(original) - i and j < len(correction) - i
        and original[len(original) - 1 - j] == correction[len(correction) - 1 - j]
    ):
        j += 1
    # expand a mid-word cut to the whole latin word on both sides
    while (
        i > 0
        and _LATIN_WORD.match(original[i - 1])
        and _LATIN_WORD.match(correction[i - 1])
    ):
        i -= 1
    while (
        j > 0
        and _LATIN_WORD.match(original[len(original) - j])
        and _LATIN_WORD.match(correction[len(correction) - j])
    ):
        j -= 1
    old = original[i: len(original) - j]
    new = correction[i: len(correction) - j]
    return old, new, i, len(original) - j


async def check_typos(
    parsed: ParsedDocument,
    *,
    route: str = "auto",
) -> tuple[list[Finding], list[Revision]]:
    ref_paras = {r.paragraph_id for r in parsed.references if r.paragraph_id}
    markers_by_para: dict[str, list[tuple[int, int]]] = {}
    for m in parsed.markers:
        markers_by_para.setdefault(m.paragraph_id, []).append((m.start, m.end))

    async def one(p: Paragraph):
        if p.id in ref_paras or _skippable(p.text):
            return [], []
        res = await chat_json(
            "typo",
            [{"role": "user", "content": _PROMPT.replace("{text}", p.text)}],
            _TypoOut,
            route=route,
        )
        findings: list[Finding] = []
        revs: list[Revision] = []
        if res.value is None:
            return findings, revs
        spans = markers_by_para.get(p.id, [])
        for item in res.value.items:
            orig = unicodedata.normalize("NFC", item.original or "")
            corr = unicodedata.normalize("NFC", item.correction or "")
            if not orig or p.text.count(orig) != 1:
                continue
            if corr == orig or _digits(corr) != _digits(orig):
                continue
            s0 = p.text.index(orig)
            if any(s0 < e and s0 + len(orig) > s for s, e in spans):
                continue
            old, new, i, j = _minimise(orig, corr)
            if not old and not new:
                continue
            a_start, a_end = s0 + i, s0 + j
            anchor = Anchor(paragraph_id=p.id, start=a_start, end=a_end)
            if Levenshtein.distance(old, new) > 2:
                findings.append(Finding(
                    id="", layer="norms", severity="low", anchor=anchor,
                    title="疑似笔误，请确认",
                    detail=f"依据：建议将「{orig}」中的「{old}」改为「{new}」。\n"
                           "建议：确认后自行修改。",
                    refs=[],
                ))
            else:
                revs.append(Revision(
                    id="", kind="typo", anchor=anchor,
                    old=old, new=new,
                    reason=item.reason or "错别字",
                ))
        return findings, revs

    results = await asyncio.gather(*[one(p) for p in parsed.paragraphs])
    findings = [f for fl, _ in results for f in fl]
    revisions = [r for _, rl in results for r in rl]
    for i, f in enumerate(findings):
        f.id = f"typ-f{i}"
    for i, r in enumerate(revisions):
        r.id = f"typ-r{i}"
    return findings, revisions
