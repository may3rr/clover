"""Overview stage: a small multi-agent pass that places the manuscript
against recent papers of the target venue.

  scout    (no model)   pick 3 similar papers from the venue — venues.py
  readers  (fast model) one per exemplar + one for the manuscript, in
                        parallel: extract each paper's "shape" — profile.py
  critic   (deep model) compare shapes + the four layers' findings and
                        give a tier per dimension and a 2–3 sentence
                        direction

The critic answers in tiers on purpose: users should read this as "where
the draft roughly stands", not as revision instructions (AGENTS §2 —
no rewriting, no suggested references).

`prepare()` runs alongside the four layers (it needs no findings);
`critique()` runs after them.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
from dataclasses import dataclass, field
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from ..cache import Cache
from ..llm.client import chat_json
from ..parse.parser import ParsedDocument
from ..schema import ExemplarPaper, Finding, Overview, OverviewDim
from ..support.sources import _fetch_pdf_text
from .profile import exemplar_counts, manuscript_profile, read_shape
from .venues import VENUES, pick_exemplars

log = logging.getLogger(__name__)

DIMS = {
    "experiments": "实验规模",
    "analysis": "分析深度",
    "literature": "文献覆盖",
    "citations": "引用可靠性",
    "completeness": "结构完整",
}
TIER_LABEL = {
    "below": "低于常见水平",
    "near": "略低于常见水平",
    "at": "达到常见水平",
    "above": "高于常见水平",
    "na": "无法判断",
}
COMMENT_MAX = 160
NOTE_MAX = 40


@dataclass
class Prepared:
    venue_id: str
    manuscript: dict
    exemplars: list[ExemplarPaper] = field(default_factory=list)
    note: str | None = None


async def prepare(parsed: ParsedDocument, venue_id: str,
                  client: httpx.AsyncClient, cache: Cache) -> Prepared:
    venue = VENUES.get(venue_id)
    stats, excerpt = manuscript_profile(parsed)
    if venue is None:
        return Prepared(venue_id, stats, note="不支持这个目标期刊")

    title = parsed.document.title or ""
    query = f"{title} {excerpt}"
    this_year = _dt.date.today().year
    picked = await pick_exemplars(
        venue, query, [this_year - 1, this_year - 2], client, cache)

    async def read_one(c) -> ExemplarPaper | None:
        text = await _fetch_pdf_text(c.pdf, client, cache)
        if not text:
            return None
        shape = await read_shape(text)
        return ExemplarPaper(
            id=c.id, title=c.title, year=c.year, url=c.url,
            stats={**shape.model_dump(), **exemplar_counts(text)},
        )

    mine, *theirs = await asyncio.gather(
        read_shape(excerpt), *(read_one(c) for c in picked))
    stats.update(mine.model_dump())
    exemplars = [e for e in theirs if e is not None]
    note = None if exemplars else f"没能获取 {venue.name} 近期论文作为参照"
    return Prepared(venue_id, stats, exemplars, note)


class _Dim(BaseModel):
    key: str
    tier: Literal["below", "near", "at", "above", "na"]
    note: str = ""


class _Verdict(BaseModel):
    overall: Literal["below", "near", "at", "above", "na"]
    dims: list[_Dim] = Field(default_factory=list)
    comment: str = ""


_CRITIC_PROMPT = """你是 {venue} 的资深审稿人，在投稿前给作者一个整体定位。你会看到：
1. 待投稿论文的结构统计（manuscript）；
2. {venue} 近两年与它主题最接近的几篇已发表论文的同类统计（exemplars）；
3. 自动引用检查的结果汇总（findings）。

把待投稿论文和这些已发表论文比较，按以下维度各给一个档次：
- experiments 实验规模：数据集、基线、表格数量
- analysis 分析深度：消融、人工评估、错误分析
- literature 文献覆盖：参考文献数量与新近程度
- citations 引用可靠性：根据 findings 中真实性与支持度问题的数量和严重程度
- completeness 结构完整：Limitations、伦理声明等该会议要求的部分
档次只能是 below（低于常见水平）、near（略低于）、at（达到）、above（高于）、na（信息不足）。每个维度的 note 用一句不超过 30 字的中文说明依据，引用具体数字。

overall 是整体档次。comment 用两到三句中文，说清整体处在什么位置、最值得投入精力的方向。

必须遵守：
- 只给档次和方向，不写逐句修改意见，不改写或续写论文内容，不推荐具体应该引用哪篇文献。
- 不知道就写 na，不要夸大，也不要贬低；这是一个粗略定位，不是审稿结论。
- 文风平实，不用感叹号，不用营销腔。

只输出 JSON：{{"overall": "...", "dims": [{{"key": "...", "tier": "...", "note": "..."}}], "comment": "..."}}"""


def summarize_findings(findings: list[Finding]) -> dict:
    out: dict[str, dict[str, int]] = {}
    for f in findings:
        out.setdefault(f.layer, {}).setdefault(f.severity, 0)
        out[f.layer][f.severity] += 1
    return out


async def critique(prep: Prepared, findings: list[Finding]) -> Overview:
    venue = VENUES.get(prep.venue_id)
    name = venue.name if venue else prep.venue_id
    base = Overview(venue_id=prep.venue_id, venue_name=name,
                    exemplars=prep.exemplars, manuscript=prep.manuscript)
    if not prep.exemplars:
        base.status = "unavailable"
        base.note = prep.note
        return base

    payload = {
        "manuscript": prep.manuscript,
        "exemplars": [{"title": e.title, "year": e.year, **e.stats}
                      for e in prep.exemplars],
        "findings": summarize_findings(findings),
    }
    r = await chat_json("overview", [
        {"role": "system", "content": _CRITIC_PROMPT.format(venue=name)},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], _Verdict)
    v = r.value
    if v is None:
        base.status = "unavailable"
        base.note = "整体评估暂时无法生成"
        return base

    given = {d.key: d for d in v.dims if d.key in DIMS}
    base.dims = [
        OverviewDim(key=k, label=label,
                    tier=given[k].tier if k in given else "na",
                    note=(given[k].note if k in given else "")[:NOTE_MAX])
        for k, label in DIMS.items()
    ]
    base.overall = v.overall
    base.comment = v.comment.strip()[:COMMENT_MAX]
    return base


async def run_overview_safe(coro) -> Overview | Prepared | None:
    """Overview is optional garnish: any failure degrades to None."""
    try:
        return await coro
    except Exception as e:  # noqa: BLE001
        log.warning("overview stage failed: %s", e)
        return None
