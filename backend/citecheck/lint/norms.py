"""规范检查（确定性规则，不调用模型）。

检查项：
- 参考文献未被正文引用；
- 正文引用编号没有对应的参考文献条目；
- 参考文献条目重复（归一化标题 token_sort_ratio >= 95）；
- 同一篇论文混用数字编号与作者-年份两种引用格式；
- GB/T 类型标识混用（部分条目有 [J]/[M] 等标签，部分没有）；
- Zotero/EndNote 管理的文献顺序与首次引用顺序不一致（只提示，
  不产生修订——排序由管理软件负责）。
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..parse.links import author_year_items, _numeric_items, unresolved_numeric
from ..parse.parser import ParsedDocument
from ..refs.structure import _TYPE_TAG_RE
from ..schema import Anchor, Finding, Reference


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def _ref_anchor(ref: Reference, para_len: dict[str, int]) -> Anchor | None:
    if not ref.paragraph_id:
        return None
    return Anchor(
        paragraph_id=ref.paragraph_id, start=0,
        end=para_len.get(ref.paragraph_id, len(ref.raw)),
    )


def check_norms(parsed: ParsedDocument) -> list[Finding]:
    findings: list[Finding] = []
    para_len = {p.id: len(p.text) for p in parsed.paragraphs}
    refs = parsed.references

    # ---- degraded honesty: nothing citable was found -------------------
    # Never emit an all-clean report for a citation-free document.
    if not parsed.markers and not refs:
        findings.append(Finding(
            id="", layer="norms", severity="medium", anchor=None,
            title="没有在这篇文档中找到引用标记和参考文献列表",
            detail="依据：正文未发现 [n]、（作者，年份）、上标或脚注形式的"
                   "引用标记，也未识别到参考文献列表。\n"
                   "建议：确认这份文件是否为待检论文；若引用由其他工具管理，"
                   "请先在文档中将引用转换为普通文本后重新体检。",
            refs=[],
        ))

    # ---- uncited references ------------------------------------------
    cited: set[str] = set()
    for m in parsed.markers:
        cited.update(m.ref_ids)
    for r in refs:
        if r.id not in cited:
            findings.append(Finding(
                id="", layer="norms", severity="medium",
                anchor=_ref_anchor(r, para_len),
                title="这篇参考文献在正文中没有被引用",
                detail="依据：正文的引用标记中没有指向这一条目的编号。\n"
                       "建议：确认是否需要保留这条参考文献；如保留，请在正文相应"
                       "论述处标注引用。",
                refs=[r.id],
            ))

    # ---- entries without a publication year --------------------------
    for r in refs:
        if r.year is None and r.origin == "list" and len(r.raw) > 40:
            findings.append(Finding(
                id="", layer="norms", severity="low",
                anchor=_ref_anchor(r, para_len),
                title="这条参考文献缺少发表年份",
                detail="依据：条目中没有找到表示发表时间的年份（会议名和 DOI 中的"
                       "年份不计）。\n建议：补全发表年份。",
                refs=[r.id],
            ))

    # ---- markers without a matching entry ----------------------------
    for m in parsed.markers:
        if m.kind not in {"numeric", "superscript", "endnote"}:
            continue
        nums = unresolved_numeric(m.raw, refs)
        if nums:
            findings.append(Finding(
                id="", layer="norms", severity="high",
                anchor=Anchor(paragraph_id=m.paragraph_id, start=m.start,
                              end=m.end),
                title="正文引用找不到对应的参考文献条目",
                detail=f"依据：标记 {m.raw.strip()} 中的编号 "
                       f"{', '.join(str(n) for n in nums)} 超出参考文献列表"
                       f"（共 {len(refs)} 条）。\n"
                       "建议：核对编号是否笔误，或补全缺失的参考文献条目。",
                refs=[],
            ))

    # author-year: a marker naming more works than it resolved to has at
    # least one citation with no matching entry
    for m in parsed.markers:
        if m.kind != "author_year":
            continue
        items = author_year_items(m.raw)
        if not items or len(set(m.ref_ids)) >= len(items):
            continue
        findings.append(Finding(
            id="", layer="norms", severity="high",
            anchor=Anchor(paragraph_id=m.paragraph_id, start=m.start,
                          end=m.end),
            title="正文引用找不到对应的参考文献条目",
            detail=f"依据：引用 {m.raw.strip()} 在参考文献列表中找不到作者和"
                   "年份都对得上的条目。\n"
                   "建议：补全缺失的参考文献条目，或核对作者姓氏与年份是否笔误。",
            refs=list(m.ref_ids),
        ))

    # ---- duplicate references ----------------------------------------
    keyed = [(i, r) for i, r in enumerate(refs) if r.title]
    for j in range(len(keyed)):
        i2, r2 = keyed[j]
        t2 = _norm_title(r2.title or "")
        for i1, r1 in keyed[:j]:
            t1 = _norm_title(r1.title or "")
            if t1 and fuzz.token_sort_ratio(t1, t2) >= 95:
                findings.append(Finding(
                    id="", layer="norms", severity="medium",
                    anchor=_ref_anchor(r2, para_len),
                    title="这条参考文献与前面的条目重复",
                    detail=f"依据：本条与第 {r1.label or i1 + 1} 条"
                           f"「{(r1.title or '')[:60]}」标题一致。\n"
                           "建议：保留其中一条，并核对正文引用指向。",
                    refs=[r1.id, r2.id],
                ))
                break

    # ---- mixed citation styles ---------------------------------------
    if parsed.document.citation_style == "mixed":
        anchor = None
        for s in parsed.sections:
            if s.heading_paragraph_id:
                anchor = Anchor(paragraph_id=s.heading_paragraph_id, start=0,
                                end=para_len.get(s.heading_paragraph_id,
                                                 len(s.title)))
                break
        findings.append(Finding(
            id="", layer="norms", severity="medium", anchor=anchor,
            title="正文混用了数字编号和作者-年份两种引用格式",
            detail="依据：同一篇论文中同时出现 [1] 式编号标记和 "
                   "(Author, 2020) 式作者-年份标记。\n"
                   "建议：按目标期刊或学校要求统一为其中一种。",
            refs=[],
        ))

    # ---- GB/T type-tag mixing -----------------------------------------
    tagged = [bool(_TYPE_TAG_RE.search(r.raw)) for r in refs]
    if any(tagged) and not all(tagged):
        for r, ok in zip(refs, tagged):
            if not ok:
                findings.append(Finding(
                    id="", layer="norms", severity="low",
                    anchor=_ref_anchor(r, para_len),
                    title="这条参考文献缺少文献类型标识",
                    detail="依据：列表中部分条目标注了 [J]、[M] 等文献类型标识，"
                           "本条没有。\n"
                           "建议：统一补齐或统一去掉类型标识。",
                    refs=[r.id],
                ))

    # ---- managed list out of first-appearance order -------------------
    if parsed.document.managed_by in {"zotero", "endnote"} and refs:
        first_seen: list[str] = []
        for m in parsed.markers:
            for rid in m.ref_ids:
                if rid not in first_seen:
                    first_seen.append(rid)
        order = [r.id for r in refs if r.id in first_seen]
        if order != first_seen:
            tool = "Zotero" if parsed.document.managed_by == "zotero" else "EndNote"
            first = refs[0]
            findings.append(Finding(
                id="", layer="norms", severity="medium",
                anchor=_ref_anchor(first, para_len),
                title=f"检测到引用由 {tool} 管理，请在该软件中刷新排序。",
                detail="依据：参考文献顺序与正文首次引用顺序不一致，但列表"
                       f"由 {tool} 字段管理，本地不生成修订。\n"
                       f"建议：在 {tool} 中刷新文献排序或切换为按引用顺序"
                       "排列的样式。",
                refs=[],
            ))

    for i, f in enumerate(findings):
        f.id = f"nrm-{i}"
    return findings
