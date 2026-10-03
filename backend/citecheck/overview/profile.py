"""Paper "shape" profiles (overview stage, step 2).

A profile is a handful of countable facts about a paper — how big the
experiments are, how deep the analysis goes, how current the literature
is. The manuscript's profile is mostly computed locally; only its
abstract, section headings and table/figure captions go to the model
(never body text — AGENTS §2). Exemplar profiles come from their public
PDFs.
"""

from __future__ import annotations

import datetime as _dt
import re
from statistics import median

from pydantic import BaseModel

from ..llm.client import chat_json
from ..parse.parser import ParsedDocument

_TABLE_CAP = re.compile(r"^\s*(Table|Tab\.)\s*(\d+)\s*[:.]", re.I)
_FIG_CAP = re.compile(r"^\s*(Figure|Fig\.)\s*(\d+)\s*[:.]", re.I)


class Shape(BaseModel):
    """What the reader model fills in; None = can't tell from the text."""
    n_datasets: int | None = None
    n_baselines: int | None = None
    has_ablation: bool | None = None
    has_human_eval: bool | None = None
    has_error_analysis: bool | None = None


_SHAPE_PROMPT = """你在统计一篇 NLP 论文的实验规模。根据给出的文本，只回答能确定的事实，不能确定的填 null，不要猜。
- n_datasets：实验用到的不同数据集 / benchmark 个数
- n_baselines：对比的基线方法个数（不含本文方法及其变体）
- has_ablation：是否有消融实验
- has_human_eval：是否有人工评估
- has_error_analysis：是否有错误分析或案例分析
只输出 JSON：{"n_datasets": int|null, "n_baselines": int|null, "has_ablation": bool|null, "has_human_eval": bool|null, "has_error_analysis": bool|null}"""


async def read_shape(text: str) -> Shape:
    r = await chat_json("profile", [
        {"role": "system", "content": _SHAPE_PROMPT},
        {"role": "user", "content": text[:16000]},
    ], Shape)
    return r.value or Shape()


def count_captions(lines: list[str]) -> tuple[int, int]:
    """Distinct table / figure numbers among caption-like lines."""
    tables = {m.group(2) for ln in lines if (m := _TABLE_CAP.match(ln))}
    figs = {m.group(2) for ln in lines if (m := _FIG_CAP.match(ln))}
    return len(tables), len(figs)


def _section_text(parsed: ParsedDocument, *titles: str) -> str:
    ids = {s.id for s in parsed.sections
           if any(t in s.title.lower() for t in titles)}
    heads = {s.heading_paragraph_id for s in parsed.sections}
    return " ".join(p.text for p in parsed.paragraphs
                    if p.section_id in ids and p.id not in heads)


def manuscript_profile(parsed: ParsedDocument) -> tuple[dict, str]:
    """(local stats, the short excerpt the reader model may see)."""
    texts = [p.text for p in parsed.paragraphs]
    n_tables, n_figs = count_captions(texts)
    captions = [t[:240] for t in texts if _TABLE_CAP.match(t) or _FIG_CAP.match(t)]
    titles = [s.title for s in parsed.sections if s.title]
    lower = " ".join(titles).lower()
    this_year = _dt.date.today().year
    years = [r.year for r in parsed.references if r.year]
    stats = {
        "words": parsed.document.word_count,
        "sections": len(parsed.sections),
        "n_tables": n_tables,
        "n_figures": n_figs,
        "n_references": len(parsed.references),
        "median_ref_year": int(median(years)) if years else None,
        "recent_ref_share": round(sum(y >= this_year - 3 for y in years)
                                  / len(years), 2) if years else None,
        "has_limitations": "limitation" in lower,
        "has_ethics": "ethic" in lower,
    }
    abstract = _section_text(parsed, "abstract")[:2000]
    excerpt = "\n".join([
        f"Title: {parsed.document.title or ''}",
        f"Abstract: {abstract}",
        "Section headings: " + " | ".join(titles),
        "Table and figure captions:",
        *captions,
    ])
    return stats, excerpt


def exemplar_counts(fulltext: str) -> dict:
    lines = re.split(r"(?<=[.!?])\s+|\n", fulltext)
    n_tables, n_figs = count_captions(lines)
    if not n_tables:  # PDF text often loses line starts — fall back to refs
        n_tables = len(set(re.findall(r"\bTable\s+(\d+)", fulltext)))
    if not n_figs:
        n_figs = len(set(re.findall(r"\bFig(?:ure|\.)\s*(\d+)", fulltext)))
    return {
        "n_tables": n_tables,
        "n_figures": n_figs,
        "has_limitations": bool(re.search(r"\bLimitations\b", fulltext)),
    }
