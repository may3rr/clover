"""支持度层编排：claims -> per-ref source text -> judge -> SupportCheck +
Finding。三层规则：

- source_kind=none：不问模型，直接 undetermined；
- label 为 supported/partial/unsupported 但 evidence 为空或无法逐字
  定位 → 降级 undetermined（§5.3）；
- Findings：unsupported=高、partial=中；每个拿不到原文的参考文献给一
  条低优先级提示（挂在参考文献段落上）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..cache import Cache
from ..config import get_settings
from ..parse.parser import ParsedDocument
from ..schema import Anchor, Claim, Finding, RefCheck, SupportCheck
from .claims import extract_claims
from .evidence import locate_evidence
from .judge import judge_claim
from .sources import build_source

log = logging.getLogger(__name__)


async def run_support(
    parsed: ParsedDocument,
    ref_checks: list[RefCheck],
    *,
    cache: Cache | None = None,
    http: httpx.AsyncClient | None = None,
) -> tuple[list[Claim], list[SupportCheck], list[Finding]]:
    matched_by_ref = {rc.ref_id: rc.matched for rc in ref_checks}
    marker_by_id = {m.id: m for m in parsed.markers}
    para_by_id = {p.id: p for p in parsed.paragraphs}
    ref_para = {r.id: r.paragraph_id for r in parsed.references}
    para_len = {p.id: len(p.text) for p in parsed.paragraphs}
    ref_ids: set[str] = {r.id for r in parsed.references}

    # ---- claim extraction (one LLM call per cited sentence) ----------
    by_para: dict[str, list] = {}
    for m in parsed.markers:
        by_para.setdefault(m.paragraph_id, []).append(m)
    claim_lists = await asyncio.gather(
        *[
            extract_claims(para_by_id[pid], sorted(ms, key=lambda m: m.start))
            for pid, ms in by_para.items()
            if pid in para_by_id
        ]
    )
    claims: list[Claim] = [c for lst in claim_lists for c in lst]
    for i, c in enumerate(claims):
        c.id = f"c{i}"

    # ---- per (claim, ref) judgement ----------------------------------
    jobs: list[tuple[Claim, str]] = []
    for c in claims:
        wanted: list[str] = []
        for mid in c.marker_ids:
            mk = marker_by_id.get(mid)
            if mk:
                for rid in mk.ref_ids:
                    if rid in ref_ids and rid not in wanted:
                        wanted.append(rid)
        for rid in wanted:
            jobs.append((c, rid))

    cache = cache or Cache(get_settings().cache_path)
    own_http = http is None
    http = http or httpx.AsyncClient(follow_redirects=True)
    try:
        checks = await asyncio.gather(
            *[
                _judge_pair(c, rid, matched_by_ref.get(rid), cache, http)
                for c, rid in jobs
            ]
        )
    finally:
        if own_http:
            await http.aclose()

    # ---- findings -----------------------------------------------------
    findings: list[Finding] = []
    no_source_refs: set[str] = set()
    for (claim, rid), check in zip(jobs, checks):
        if check.label == "unsupported":
            findings.append(
                Finding(
                    id="", layer="support", severity="high",
                    anchor=Anchor(paragraph_id=claim.paragraph_id,
                                  start=claim.start, end=claim.end),
                    title="被引文献不支持这条论断",
                    detail=f"依据：{check.rationale or '模型判断原文不支持该论断'}\n"
                           "建议：核对论断与文献内容，考虑删除引用或修改论断。",
                    refs=[rid],
                )
            )
        elif check.label == "partial":
            findings.append(
                Finding(
                    id="", layer="support", severity="medium",
                    anchor=Anchor(paragraph_id=claim.paragraph_id,
                                  start=claim.start, end=claim.end),
                    title="被引文献只部分支持这条论断",
                    detail=f"依据：{check.rationale or '原文只覆盖论断的一部分'}\n"
                           "建议：检查论断中未被覆盖的部分是否需要另外的文献支撑。",
                    refs=[rid],
                )
            )
        if check.source_kind == "none":
            no_source_refs.add(rid)
    for rid in sorted(no_source_refs):
        pid = ref_para.get(rid) or ""
        findings.append(
            Finding(
                id="", layer="support", severity="low",
                anchor=Anchor(paragraph_id=pid, start=0, end=para_len.get(pid, 0)),
                title="未能获取这篇文献的原文，相关论断无法判断",
                detail="依据：未找到可用的摘要或开放全文。\n"
                       "建议：人工核对引用该文献的论断。",
                refs=[rid],
            )
        )
    for i, f in enumerate(findings):
        f.id = f"sup-{i}"
    return claims, list(checks), findings


async def evaluate_with_excerpt(
    claim: Claim, ref_id: str, excerpt: str, title: str | None, source_kind: str
) -> SupportCheck:
    """Judge + §5.3 evidence verification on a ready excerpt."""
    out = await judge_claim(claim.text, title, excerpt)
    if out is None:
        return SupportCheck(
            claim_id=claim.id, ref_id=ref_id, label="undetermined",
            evidence=None, source_kind=source_kind,  # type: ignore[arg-type]
            rationale="模型输出无效，未作判断",
            source_title=title, source_excerpt=excerpt,
        )
    label = out.label
    evidence = out.evidence
    rationale = out.rationale
    span = None
    if label in {"supported", "partial", "unsupported"}:
        if not evidence or not evidence.strip():
            label, evidence = "undetermined", None
            rationale = "模型未给出原文证据"
        else:
            span = locate_evidence(evidence, excerpt)
            if span is None:
                label, evidence = "undetermined", None
                rationale = "证据未能在原文中定位"
    return SupportCheck(
        claim_id=claim.id, ref_id=ref_id, label=label, evidence=evidence,
        source_kind=source_kind,  # type: ignore[arg-type]
        rationale=rationale, source_title=title,
        source_excerpt=excerpt, evidence_span=span,
    )


async def _judge_pair(
    claim: Claim, ref_id: str, matched: dict | None, cache: Cache, http
) -> SupportCheck:
    source = await build_source(matched, claim.text, cache=cache, client=http)
    if source.kind == "none" or not source.excerpt:
        return SupportCheck(
            claim_id=claim.id, ref_id=ref_id, label="undetermined",
            evidence=None, source_kind="none",
            rationale="未能获取被引文献原文", source_title=source.title,
        )
    return await evaluate_with_excerpt(
        claim, ref_id, source.excerpt,
        matched.get("title") if matched else None, source.kind,
    )
