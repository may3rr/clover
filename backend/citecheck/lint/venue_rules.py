"""目标期刊的硬性投稿要求（benchmarks/venues/<id>.toml 的 [rules]）。

Deterministic, no model. Every finding names the journal and quotes the
rule, and none of them edits the manuscript — these are 批注 only.
"""

from __future__ import annotations

import re
from datetime import date

from ..parse.parser import ParsedDocument
from ..schema import Anchor, Finding

_CJK = re.compile(r"[一-鿿]")


def _ref_anchor(parsed: ParsedDocument, ref) -> Anchor | None:
    if not ref.paragraph_id:
        return None
    n = next((len(p.text) for p in parsed.paragraphs if p.id == ref.paragraph_id), len(ref.raw))
    return Anchor(paragraph_id=ref.paragraph_id, start=0, end=n)


def _heading_anchor(parsed: ParsedDocument, title: str) -> Anchor | None:
    sec = next((s for s in parsed.sections if re.sub(r"[:：\s]", "", s.title) == title), None)
    if sec is None or not sec.heading_paragraph_id:
        return None
    n = next((len(p.text) for p in parsed.paragraphs if p.id == sec.heading_paragraph_id), 0)
    return Anchor(paragraph_id=sec.heading_paragraph_id, start=0, end=n)


def check_venue_rules(parsed: ParsedDocument, venue: dict,
                      year: int | None = None) -> list[Finding]:
    rules = venue.get("rules", {})
    name = venue["name"]
    out: list[Finding] = []

    def add(severity, title, detail, anchor=None, refs=None):
        out.append(Finding(id="", layer="norms", severity=severity, anchor=anchor,
                           title=title, detail=detail, refs=refs or []))

    refs = [r for r in parsed.references if r.origin == "list"]
    ref_heading = _heading_anchor(parsed, "参考文献") or _heading_anchor(parsed, "References")

    if (n := rules.get("min_refs")) and refs and len(refs) < n:
        add("medium", f"参考文献少于《{name}》要求的 {n} 条",
            f"依据：《{name}》要求参考文献不少于 {n} 条，本文共 {len(refs)} 条。\n"
            "建议：确认是否遗漏了正文实际参考的文献。", ref_heading)

    span = rules.get("recent_share")
    years = [r.year for r in refs if r.year]
    if span and len(years) >= 5:
        k = rules.get("recent_years", 3)
        now = year or date.today().year
        share = sum(1 for y in years if y > now - k) / len(years)
        lo, hi = span
        if not lo <= share <= hi:
            add("low", f"近{k}年文献占比不在《{name}》建议的范围内",
                f"依据：《{name}》建议近{k}年（{now - k + 1}—{now}年）的文献占 "
                f"{lo:.0%}～{hi:.0%}，本文为 {share:.0%}（{len(years)} 条有年份的文献）。\n"
                "建议：作者自行判断是否需要调整，本工具不推荐具体文献。", ref_heading)

    if rules.get("translation_required"):
        for r in refs:
            if r.lang == "zh" and not r.translation:
                add("low", "中文文献缺少英文译文",
                    f"依据：《{name}》要求中文文献在条目后用圆括号附英文译文，"
                    "以文献源自带的英文为准。\n建议：补上该文献的英文题录。",
                    _ref_anchor(parsed, r), [r.id])

    texts = [p.text.strip() for p in parsed.paragraphs]
    for label in rules.get("statements", []):
        if not any(t.startswith(label) for t in texts):
            add("medium", f"缺少{label}",
                f"依据：《{name}》要求在参考文献之后给出{label}。\n"
                f"建议：在文末补写{label}。")

    labels = rules.get("abstract_labels")
    if labels:
        abstract = next((s for s in parsed.sections
                         if re.sub(r"[:：\s]", "", s.title) == "摘要"), None)
        if abstract is not None:
            body = "".join(p.text for p in parsed.paragraphs if p.section_id == abstract.id)
            missing = [x for x in labels
                       if not re.search(rf"[\[【［]\s*{x}\s*[\]】］]", body)]
            if missing and _CJK.search(body):
                add("low", "结构式摘要缺少要素",
                    f"依据：《{name}》要求结构式摘要，本文摘要缺少"
                    + "、".join(f"【{x}】" for x in missing) + "。\n"
                    "建议：按该刊《结构式文摘写作要求》补齐。",
                    _heading_anchor(parsed, "摘要"))
    return out
