"""期刊对标的模型细化：标题归类、研究要素、范文的引用功能。

Three reads, all with the fast model, all cached like every model call
(an exemplar folder costs once):

- heading types for the titles the keyword table cannot place
  ("3 IG-RAG框架设计" -> method), the manuscript's and the exemplars' alike;
- research elements (datasets, baselines, ablation, case study, human
  evaluation) from the title, abstract, section headings and captions —
  the same parts on both sides, and for the manuscript nothing beyond
  what the overview stage already sends. Every value carries a verbatim
  quote that must be found in the text it was read from (AGENTS §5.3);
  a quote that cannot be located drops the value to unknown;
- citation functions of the exemplars' citing sentences, with the same
  prompt the distribution layer uses for the manuscript, so the two
  shares are counted the same way.
"""

from __future__ import annotations

import asyncio
import logging
import re

from pydantic import BaseModel, Field

from ..parse.headings import canonical_for, is_ref_heading
from ..parse.parser import ParsedDocument
from ..support.evidence import locate_evidence
from .venue import manuscript_abstract

log = logging.getLogger(__name__)

_CANONS = {"intro", "related", "method", "experiment", "discussion", "conclusion", "other"}
_FRONT = re.compile(r"^(摘\s*要|abstract|关键词|keywords|中图分类号|引用本文|参考文献|"
                    r"references|致谢|附录|作者贡献|利益冲突|支撑数据)", re.I)

# --------------------------------------------------------------- headings

_HEAD_PROMPT = """下面是论文正文的一级章节标题。判断每个标题对应的章节类型，取值仅限：
intro（引言）、related（相关研究或文献综述）、method（方法、模型、框架或研究设计）、
experiment（实验、实证、评测、案例应用或结果）、discussion（讨论）、conclusion（结论、结语、总结与展望）、other（都不是）。
以 JSON 输出：{"items": [{"i": 1, "canonical": "method"}]}

标题：
"""


class _HeadItem(BaseModel):
    i: int = 0
    canonical: str = ""


class _HeadOut(BaseModel):
    items: list[_HeadItem] = Field(default_factory=list)


async def classify_headings(titles: list[str]) -> dict[str, str]:
    """title -> canonical for titles the keyword table maps to other."""
    from ..llm import client

    todo = sorted({t for t in titles if t and canonical_for(t) == "other"
                   and not _FRONT.match(t.strip()) and not is_ref_heading(t)})
    out: dict[str, str] = {}

    async def batch(chunk: list[str]):
        listing = "\n".join(f"{k}. {t}" for k, t in enumerate(chunk, 1))
        res = await client.chat_json("structure", [{"role": "user",
                                                    "content": _HEAD_PROMPT + listing}], _HeadOut)
        for it in (res.value.items if res.value else []):
            if 1 <= it.i <= len(chunk) and it.canonical in _CANONS:
                out[chunk[it.i - 1]] = it.canonical

    await asyncio.gather(*(batch(todo[i:i + 40]) for i in range(0, len(todo), 40)))
    return out


# --------------------------------------------------------------- elements

# key: (label, kind). The number of baselines was dropped after the F24
# check: abstracts and captions rarely list them all (demo/testset/venue_bench)
ELEMENTS: dict[str, tuple[str, str]] = {
    "n_datasets": ("数据集个数", "number"),
    "has_ablation": ("消融实验", "bool"),
    "has_case_study": ("案例或错误分析", "bool"),
    "has_human_eval": ("人工评估", "bool"),
}
# validated well enough to raise a finding; the others are shown only
ELEMENT_FINDINGS = {"n_datasets", "has_ablation"}

_ELEM_PROMPT = """你在统计一篇论文的研究要素。下面给出论文的标题、摘要、章节标题和图表题注。只根据给出的文字回答，不能确定的填 null，不要猜。
- n_datasets：实验用到的不同数据集或语料的个数
- has_ablation：是否有消融实验，即去掉或替换本文方法的某个组成部分后比较效果；不同方法之间、不同参数之间的对比不算
- has_case_study：是否有案例分析或错误分析，即对具体样例的结果逐个分析；只展示数据样例、框架图或提示模板不算
- has_human_eval：是否由人对方法的输出质量打分或判断；人工标注的训练数据、人类撰写的语料都不算
每一项给出 value 和 evidence。evidence 从论文的标题、摘要、某个章节标题或某条题注中逐字摘录一小段作为依据，不超过 40 字，不要包含“摘要：”“章节标题：”这类栏目名。
value 为 null，或布尔项为 false 时，evidence 填 null。
只输出 JSON：{"n_datasets": {"value": 2, "evidence": "..."}, "has_ablation": {...}, "has_case_study": {...}, "has_human_eval": {...}}

论文：
"""


class _Item(BaseModel):
    value: int | bool | None = None
    evidence: str | None = None


class _ElemOut(BaseModel):
    n_datasets: _Item = Field(default_factory=_Item)
    has_ablation: _Item = Field(default_factory=_Item)
    has_case_study: _Item = Field(default_factory=_Item)
    has_human_eval: _Item = Field(default_factory=_Item)


def excerpt_parts(title: str | None, abstract: str | None, headings: list[str],
                  captions: list[str]) -> list[str]:
    """The pieces a research element may be quoted from."""
    return [x for x in [title or "", abstract or "", *headings, *captions] if x.strip()]


def excerpt(title: str | None, abstract: str | None, headings: list[str],
            captions: list[str], limit: int = 6000) -> str:
    parts = [f"标题：{title or ''}", f"摘要：{abstract or ''}",
             "章节标题：" + "；".join(headings), "图表题注：\n" + "\n".join(captions)]
    return "\n".join(parts)[:limit]


async def read_elements(parts: list[str], text: str) -> dict[str, dict]:
    """key -> {"value": float | None, "quote": str | None}. ``text`` is
    what the model reads, ``parts`` the pieces it is built from: a "yes"
    or a count needs a quote found verbatim inside one piece, else the
    value becomes unknown (AGENTS §5.3); a "no" needs no quote."""
    from ..llm import client

    res = await client.chat_json("profile", [{"role": "user", "content": _ELEM_PROMPT + text}],
                                 _ElemOut)
    out: dict[str, dict] = {}
    for key, (_label, kind) in ELEMENTS.items():
        it: _Item = getattr(res.value, key) if res.value else _Item()
        v, q = it.value, (it.evidence or "").strip() or None
        if kind == "bool":
            v = v if isinstance(v, bool) else None
        elif isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 50:
            v = None
        positive = v is True or (kind == "number" and v is not None)
        if positive and (q is None or not any(locate_evidence(q, x) for x in parts)):
            v, q = None, None  # 证据未能在原文中定位 -> unknown
        if not positive:
            q = None
        out[key] = {"value": None if v is None else float(v), "quote": q}
    return out


def manuscript_parts(parsed: ParsedDocument) -> tuple[list[str], str]:
    headings = [s.title for s in parsed.sections
                if s.title and s.heading_paragraph_id and not _FRONT.match(s.title.strip())]
    captions = [p.text[:120] for p in parsed.paragraphs if p.caption]
    args = (parsed.document.title, manuscript_abstract(parsed), headings, captions)
    return excerpt_parts(*args), excerpt(*args)


def exemplar_parts(prof: dict) -> tuple[list[str], str]:
    args = (prof.get("title"), prof.get("abstract"),
            [h["title"] for h in prof.get("headings", [])],
            [c["text"] for c in prof.get("captions", [])])
    return excerpt_parts(*args), excerpt(*args)


# -------------------------------------------------------------- functions

_MARKER_RE = re.compile(r"\[(\d{1,3}(?:\s*[-–,，]\s*\d{1,3})*)\]")


async def exemplar_functions(sentences: list[dict]) -> dict[str, int]:
    """Citation-function counts over every marker in the citing
    sentences, in chunks of a dozen sentences."""
    from ..llm import client
    from .layer import _FUNC_PROMPT, _FUNCS, _FuncOut

    counts = {f: 0 for f in _FUNCS}

    async def chunk(sents: list[dict]):
        k = 0

        def tag(_m):
            nonlocal k
            k += 1
            return f"⟦m{k}⟧"

        text = "".join(_MARKER_RE.sub(tag, s["text"]) for s in sents)
        if not k:
            return
        res = await client.chat_json("function", [{"role": "user", "content":
                                     _FUNC_PROMPT.replace("{text}", text)}], _FuncOut)
        seen: set[str] = set()
        for it in (res.value.items if res.value else []):
            if it.function in counts and it.marker_id not in seen and \
                    re.fullmatch(r"m\d+", it.marker_id or "") and int(it.marker_id[1:]) <= k:
                seen.add(it.marker_id)
                counts[it.function] += 1

    await asyncio.gather(*(chunk(sentences[i:i + 12]) for i in range(0, len(sentences), 12)))
    return counts


async def enrich(prof: dict) -> dict:
    """Model reads of one exemplar: {"elements": …, "functions": …}."""
    elements, functions = await asyncio.gather(
        read_elements(*exemplar_parts(prof)), exemplar_functions(prof.get("sentences", [])))
    return {"elements": elements, "functions": functions}
