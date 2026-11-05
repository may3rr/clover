"""错别字检查：每个正文段落一次 `typo` 任务调用。

只收集笔误：错别字、明显拼写错误、叠字（如"的的"）。不允许模型改
语法、措辞、风格、术语、专名、引用标记、数字或公式。

返回项校验与最小化：
- original 必须在段落中恰好出现一次（逐字），否则丢弃；
- correction 与 original 相同、改动了数字、或覆盖引用标记区间 → 丢弃；
- 去掉公共前后缀得到最小编辑区间；拉丁单词扩展到整个词边界；
- 中文改动所在的三字窗口在全文出现两次以上 → 视为作者的术语，丢弃；
- 最小编辑距离 > 2 → 不生成修订，给一条低优先级 finding
  "疑似笔误，请确认"，detail 中给出建议文本；
- 否则生成 Revision(kind="typo")。
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Callable

from pydantic import BaseModel, Field
from rapidfuzz.distance import Levenshtein

from ..llm.client import chat_json
from ..parse.parser import ParsedDocument
from ..schema import Anchor, Finding, Paragraph, Revision

_MATHY = re.compile(r"[0-9=+\-*/^(){}\[\]<>_\\]")
_LATIN_WORD = re.compile(r"[A-Za-z0-9]")
_CJK_CHAR = re.compile(r"[一-鿿]")
_MIN_LEN = 10

# 规范词对：old/new 都是合法汉语词，改写属于覆盖作者用词，绝不修订
# （zh_eval 实录：期刊官方模板"AI 使用申明"被模型改成"声明"）
_NEVER_REVISE = {"申明"}

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


def _words(s: str) -> list[str]:
    return re.sub(r"[^\w\s]|_", "", s).split()


def _out_of_scope(text: str, old: str, new: str, start: int, end: int) -> bool:
    """Edits the prompt asks the model not to make, which it makes anyway
    (the clean corpus runs: 154 typo revisions on human-written papers):

    - punctuation or spacing only, the words unchanged ('error' ->
      'error.', '6 ' -> '6', ', ' -> '，', 'GPU’s' -> 'GPUs');
    - a deletion of a whole word or of Chinese characters that is not a
      doubling ('10万' -> '10', '敦煌' -> ''): removing content is not
      fixing a slip, and the product never deletes the author's words.
      '的的' -> '的' and a stray letter inside a word stay.
    Splitting a run-together word ('Schoolof' -> 'School of') changes the
    words and stays a revision."""
    if _words(old) == _words(new):
        return True
    # the edit only removes text: what is removed must be a doubling
    new = new.strip()
    if len(new) < len(old) and (old.startswith(new) or old.endswith(new)):
        if old.startswith(new):
            start += len(new)
        else:
            end -= len(new)
        o = text[start:end].strip()
        if not o:
            return False
        # a stray letter inside a latin word ('helllo', 'them' -> 'the') is
        # a slip; removing a whole word or any Chinese character is not
        latin = o.isalpha() and not _CJK_CHAR.search(o)
        joined = ((start > 0 and text[start - 1].isalpha())
                  or (end < len(text) and text[end].isalpha()))
        if latin and joined:
            return False
        doubled = (text[end:end + len(o)] == o
                   or text[max(0, start - len(o)):start] == o
                   or text[end:].lstrip().startswith(o + " ")
                   or text[:start].rstrip().endswith(" " + o))
        return not doubled
    return False


_LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z'’\-]*")


def _count_word(w: str, doc_text: str) -> int:
    return len(re.findall(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", doc_text))


def _overreach(doc_text: str, text: str, old: str, new: str,
               start: int, end: int) -> bool:
    """Latin-script edits the clean-corpus ground truth found wrong every
    time (demo/testset/ground_truth/summary.md §3). Each rule was checked
    against the labels: it removes only false alarms, and none of the
    injected typos.

    - a pure insertion of a word or symbol ('' -> 'X'): LaTeX drops \\ref
      and math when rendering and the model fills the gap; adding words
      is writing, not fixing a slip. A letter added inside a word stays;
    - a case-only change in an all-lowercase paragraph ('dani alves' ->
      'Dani Alves'): a lower-cased dataset sample quoted verbatim;
    - an author's term: a non-lowercase word the manuscript uses twice or
      more, replaced by a word it never uses ('Rewon' -> 'Rezwon',
      'Table' -> 'Tables' after a dropped \\ref). Lowercase words are
      exempt, since real-word slips ('expect' for 'except') live there."""
    if _CJK_CHAR.search(old + new):
        return False
    if not old.strip():
        joined = (start > 0 and text[start - 1].isalpha()
                  and end < len(text) and text[end].isalpha())
        return not joined
    if old != new and old.casefold() == new.casefold():
        letters = [c for c in text if c.isalpha()]
        upper = sum(c.isupper() for c in letters)
        return upper < 0.01 * max(len(letters), 1)
    old_w = [w for w in _LATIN_TOKEN.findall(old)
             if len(w) >= 4 and w not in _LATIN_TOKEN.findall(new)]
    new_w = [w for w in _LATIN_TOKEN.findall(new)
             if w not in _LATIN_TOKEN.findall(old)]
    return (bool(old_w) and bool(new_w) and not old.islower()
            and all(_count_word(w, doc_text) >= 2 for w in old_w)
            and all(_count_word(w, doc_text) == 0 for w in new_w))


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
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[Finding], list[Revision]]:
    """progress(done, total) fires as each paragraph finishes."""
    ref_paras = {r.paragraph_id for r in parsed.references if r.paragraph_id}
    doc_text = "\n".join(p.text for p in parsed.paragraphs)
    markers_by_para: dict[str, list[tuple[int, int]]] = {}
    for m in parsed.markers:
        markers_by_para.setdefault(m.paragraph_id, []).append((m.start, m.end))

    async def one(p: Paragraph):
        # table cells are mostly numbers and labels: only prose-length
        # cells are worth a model call
        if p.id in ref_paras or _skippable(p.text) or (
                p.cell is not None and len(p.text) < 60):
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
            # 规范词清单：词在 original/correction 之间的出现状态翻转，
            # 即是对该词的改写（如 申明→声明），无论最小编辑区间怎么切
            if any((w in orig) != (w in corr) for w in _NEVER_REVISE):
                continue
            s0 = p.text.index(orig)
            if any(s0 < e and s0 + len(orig) > s for s, e in spans):
                continue
            old, new, i, j = _minimise(orig, corr)
            if not old and not new:
                continue
            a_start, a_end = s0 + i, s0 + j
            if _out_of_scope(p.text, old, new, a_start, a_end):
                continue
            if _overreach(doc_text, p.text, old, new, a_start, a_end):
                continue
            # a Chinese "typo" whose surroundings recur elsewhere in the
            # manuscript is the author's term (决策化模型 ×10, 可分流性 ×7),
            # not a slip — never revise a word used consistently
            if old and _CJK_CHAR.search(old + new):
                window = p.text[max(0, a_start - 1):a_end + 1]
                if doc_text.count(window) >= 2:
                    continue
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

    total = len(parsed.paragraphs)
    done = 0

    async def counted(p: Paragraph):
        nonlocal done
        try:
            return await one(p)
        finally:
            done += 1
            if progress is not None:
                progress(done, total)

    results = await asyncio.gather(*[counted(p) for p in parsed.paragraphs])
    findings = [f for fl, _ in results for f in fl]
    revisions = [r for _, rl in results for r in rl]
    for i, f in enumerate(findings):
        f.id = f"typ-f{i}"
    for i, r in enumerate(revisions):
        r.id = f"typ-r{i}"
    return findings, revisions
