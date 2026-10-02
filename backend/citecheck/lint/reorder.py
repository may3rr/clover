"""参考文献重排与正文引用编号（确定性，不调用模型）。

重排语义（导出层严格依赖）：

- 目标顺序：
  - 数字编号文献按正文首次引用顺序排列（同一标记内按列出顺序），
    未被引用的条目保持原有相对顺序排在末尾；
  - 作者-年份文献按首作者姓氏排序（中文姓氏按拼音），接受
    "中文在前"或"整体混排拼音序"两种现状，否则目标为混排拼音序。
- 取目标顺序中各条目的旧位置构成序列，求最长递增子序列（LIS）。
  LIS 中的条目原地不动，其余条目为"移动条目"。
- 移动条目 -> Revision(kind="ref_reorder", anchor=整个参考文献段落
  [0, len]，old=原段落文本，new=段落文本中数字标签替换为新编号后的
  文本（无字面标签时与 old 相同），move_after=目标顺序中前一条目的
  paragraph_id，若成为第一条则为 "__start__")。导出层按目标顺序依
  次处理移动条目，把每条副本插入到其前驱当前元素之后（前驱本身也
  是移动条目时，插在其已插入副本之后）；"__start__" 插入到第一个
  原始参考文献段落之前。
- 原地保留但标签编号变化的条目 -> Revision(kind="ref_reorder",
  anchor=仅标签数字区间，old，new，move_after=None)，即原地编辑。
- 标记重编号：新编号取目标顺序位置，标记内编号排序去重后重新写
  出——连续 >=3 个收缩为 a-b，2 个保持 a,b；保留原括号类型、连字
  符与分隔符空格；上标无括号标记保持无括号形式。仅当文本变化时产
  生 Revision(kind="marker_renumber")。
- Zotero/EndNote 管理的文档不产生任何 ref_reorder/marker_renumber
  （norms.py 给出提示性 finding）。
"""

from __future__ import annotations

import bisect
import re
import unicodedata

from pypinyin import lazy_pinyin

from ..parse.links import _numeric_items, _ref_first_surname, unresolved_numeric
from ..parse.parser import ParsedDocument
from ..schema import Anchor, Reference, Revision

_SEP_RE = re.compile(r"[,，、;；]\s*|、")
_DASH_RE = re.compile(r"\d(\s*[-–—~～]\s*)\d")
_OPENERS = "([（【［"
_CLOSERS = ")])】］"
_LABEL_HEAD = re.compile(r"^\s*[\[\(（【［]?\d{1,3}[\]\)）】］]?\s*[\.、]?")
_ZH = re.compile(r"[一-鿿]")


def _lis_indices(seq: list[int]) -> list[int]:
    """Indices of one longest increasing subsequence of ``seq``."""
    tails: list[int] = []
    tail_i: list[int] = []
    prev = [-1] * len(seq)
    for i, x in enumerate(seq):
        p = bisect.bisect_left(tails, x)
        if p == len(tails):
            tails.append(x)
            tail_i.append(i)
        else:
            tails[p] = x
            tail_i[p] = i
        prev[i] = tail_i[p - 1] if p > 0 else -1
    out: list[int] = []
    k = tail_i[-1] if tail_i else -1
    while k >= 0:
        out.append(k)
        k = prev[k]
    return out[::-1]


def _label_digits_span(
    text: str, auto_label: str | None = None
) -> tuple[int, int] | None:
    """(start, end) of the digit run inside a leading LITERAL reference
    label. When the paragraph's leading label is virtual (auto-numbering
    renders it — ``auto_label``), the match must start past the virtual
    prefix; virtual digits are Word-managed and never rewritten."""
    m = _LABEL_HEAD.match(text)
    if not m:
        return None
    d = re.search(r"\d+", m.group(0))
    if not d:
        return None
    s, e = m.start() + d.start(), m.start() + d.end()
    if auto_label and s < len(auto_label):
        return None
    return s, e


def _runs(nums: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for n in nums:
        if out and n == out[-1][-1] + 1:
            out[-1].append(n)
        else:
            out.append([n])
    return out


def _format_marker(raw: str, nums: list[int]) -> str:
    """Rewrite the number list in ``raw`` as ``nums``, preserving
    brackets, dash char, separator and surrounding whitespace."""
    lead = raw[: len(raw) - len(raw.lstrip())]
    trail = raw[len(raw.rstrip()):]
    body = raw.strip()
    opener = closer = ""
    if body and body[0] in _OPENERS and body[-1] in _CLOSERS:
        opener, closer = body[0], body[-1]
    dm = _DASH_RE.search(body)
    dash = dm.group(1) if dm else "-"
    sm = _SEP_RE.search(body)
    sep = sm.group(0) if sm else ","
    parts: list[str] = []
    for run in _runs(nums):
        if len(run) >= 3:
            parts.append(f"{run[0]}{dash}{run[-1]}")
        else:
            parts.extend(str(n) for n in run)
    return lead + opener + sep.join(parts) + closer + trail


def _move_revisions(
    refs: list[Reference],
    target: list[str],
    new_num: dict[str, int] | None,
    para_text: dict[str, str],
    auto_labels: dict[str, str] | None = None,
) -> list[Revision]:
    """LIS split + ref_reorder revisions for one target order."""
    auto_labels = auto_labels or {}
    old_pos = {r.id: i for i, r in enumerate(refs)}
    ref_by_id = {r.id: r for r in refs}
    seq = [old_pos[rid] for rid in target]
    keep = {target[i] for i in _lis_indices(seq)}
    revs: list[Revision] = []
    for k, rid in enumerate(target):
        ref = ref_by_id[rid]
        text = para_text.get(ref.paragraph_id or "", ref.raw)
        span = _label_digits_span(
            text, auto_labels.get(ref.paragraph_id or ""))
        if rid in keep:
            if new_num and span and ref.label and text[span[0]:span[1]] != str(new_num[rid]):
                revs.append(Revision(
                    id="", kind="ref_reorder",
                    anchor=Anchor(paragraph_id=ref.paragraph_id or "",
                                  start=span[0], end=span[1]),
                    old=text[span[0]:span[1]], new=str(new_num[rid]),
                    reason="文献重排后的新编号", move_after=None,
                ))
            continue
        new_text = text
        if new_num and span:
            new_text = text[: span[0]] + str(new_num[rid]) + text[span[1]:]
        move_after = (
            ref_by_id[target[k - 1]].paragraph_id if k > 0 else "__start__"
        )
        revs.append(Revision(
            id="", kind="ref_reorder",
            anchor=Anchor(paragraph_id=ref.paragraph_id or "",
                          start=0, end=len(text)),
            old=text, new=new_text,
            reason="按正文首次引用顺序重排"
            if new_num else "按首作者姓氏排序",
            move_after=move_after,
        ))
    return revs


def _ay_key(ref: Reference) -> str:
    s = _ref_first_surname(ref) or ""
    s = unicodedata.normalize("NFKC", s).strip().lower()
    if _ZH.search(s):
        return "".join(lazy_pinyin(s))
    return s


def _author_year_order(refs: list[Reference]) -> list[str] | None:
    """Target order for author-year lists, or None if already sorted."""
    keyed = [(r, _ZH.search(_ref_first_surname(r) or "") is not None)
             for r in refs]
    mixed = sorted(keyed, key=lambda t: _ay_key(t[0]))
    zh_first = sorted(keyed, key=lambda t: (0 if t[1] else 1, _ay_key(t[0])))
    cur = [r.id for r in refs]
    if cur == [r.id for r, _ in zh_first] or cur == [r.id for r, _ in mixed]:
        return None
    return [r.id for r, _ in mixed]


def plan_reorder(parsed: ParsedDocument) -> list[Revision]:
    """Revisions to bring the reference list and markers into order."""
    # only bibliography-block entries participate; footnote-promoted
    # references are anchored at their citing paragraph and must never
    # move or renumber (their mark text is virtual)
    refs = [r for r in parsed.references if r.origin == "list"]
    if not refs or parsed.document.managed_by:
        return []
    list_ids = {r.id for r in refs}
    para_text = {p.id: p.text for p in parsed.paragraphs}
    auto_labels = parsed.auto_labels
    revs: list[Revision] = []

    if parsed.document.citation_style == "author_year":
        target = _author_year_order(refs)
        if target is None:
            return []
        revs += _move_revisions(refs, target, None, para_text, auto_labels)
        return revs

    if parsed.document.citation_style != "numeric":
        return []

    # ---- numeric ------------------------------------------------------
    target: list[str] = []
    for m in parsed.markers:
        for rid in m.ref_ids:
            if rid in list_ids and rid not in target:
                target.append(rid)
    target += [r.id for r in refs if r.id not in target]
    if [r.id for r in refs] == target:
        return []

    new_num = {rid: i + 1 for i, rid in enumerate(target)}
    revs += _move_revisions(refs, target, new_num, para_text, auto_labels)

    for m in parsed.markers:
        if m.kind not in {"numeric", "superscript"}:
            continue
        nums_old = set(_numeric_items(m.raw))
        if unresolved_numeric(m.raw, refs):
            continue  # missing-entry markers are norms findings, not edits
        if len(m.ref_ids) != len(nums_old):
            continue
        new_nums = sorted({new_num[rid] for rid in m.ref_ids
                           if rid in new_num})
        if not new_nums:
            continue
        new_raw = _format_marker(m.raw, new_nums)
        if new_raw != m.raw:
            revs.append(Revision(
                id="", kind="marker_renumber",
                anchor=Anchor(paragraph_id=m.paragraph_id, start=m.start,
                              end=m.end),
                old=m.raw, new=new_raw,
                reason="按正文首次引用顺序重新编号",
            ))

    for i, r in enumerate(revs):
        r.id = f"rev-{i}"
    return revs
