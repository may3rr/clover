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
from .judge import JudgeOut, judge_claim
from .sources import build_source

log = logging.getLogger(__name__)


class SupportRun:
    """Incremental support layer (T6): claim extraction starts as soon as
    the run is created; ``add_check`` queues that reference's judge pairs
    the moment its RefCheck lands (verification and judging overlap).
    ``finish`` also covers refs that never got a check (authenticity
    failed -> undetermined / source_kind=none)."""

    def __init__(
        self,
        parsed: ParsedDocument,
        *,
        cache: Cache | None = None,
        http: httpx.AsyncClient | None = None,
    ):
        self._parsed = parsed
        self._cache = cache or Cache(get_settings().cache_path)
        self._own_http = http is None
        self._http = http or httpx.AsyncClient(follow_redirects=True)
        self._matched: dict[str, dict | None] = {}
        self._out: dict[tuple[str, str], SupportCheck] = {}
        self._queued: set[tuple[str, str]] = set()
        self._queue_tasks: list[asyncio.Task] = []
        self._judge_tasks: list[asyncio.Task] = []
        # claim extraction doesn't need verification — start immediately
        self._claims_task = asyncio.create_task(self._extract())

    async def _extract(self) -> list[Claim]:
        parsed = self._parsed
        para_by_id = {p.id: p for p in parsed.paragraphs}
        by_para: dict[str, list] = {}
        for m in parsed.markers:
            by_para.setdefault(m.paragraph_id, []).append(m)
        claim_lists = await asyncio.gather(
            *[
                extract_claims(
                    para_by_id[pid], sorted(ms, key=lambda m: m.start))
                for pid, ms in by_para.items()
                if pid in para_by_id
            ]
        )
        claims: list[Claim] = [c for lst in claim_lists for c in lst]
        for i, c in enumerate(claims):
            c.id = f"c{i}"
        # (claim, ref) job list in claims order — shared by add_check and
        # finish() so each pair is judged exactly once
        marker_by_id = {m.id: m for m in parsed.markers}
        ref_ids: set[str] = {r.id for r in parsed.references}
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
        self._jobs = jobs
        return claims

    def add_check(self, rc: RefCheck) -> None:
        """Queue this ref's judge pairs (claims may still be extracting —
        the queue task waits for them)."""
        self._matched[rc.ref_id] = rc.matched
        self._queue_tasks.append(
            asyncio.create_task(self._queue_ref(rc.ref_id)))

    async def _queue_ref(self, rid: str) -> None:
        await self._claims_task
        for c, rrid in self._jobs:
            if rrid == rid:
                self._spawn(c, rid)

    def _spawn(self, c: Claim, rid: str) -> None:
        if (c.id, rid) in self._queued:
            return
        self._queued.add((c.id, rid))
        self._judge_tasks.append(asyncio.create_task(self._do(c, rid)))

    async def _do(self, c: Claim, rid: str) -> None:
        self._out[(c.id, rid)] = await _judge_pair(
            c, rid, self._matched.get(rid), self._cache, self._http)

    async def finish(
        self,
    ) -> tuple[list[Claim], list[SupportCheck], list[Finding]]:
        claims = await self._claims_task
        # refs that never produced a check -> undetermined pairs
        for c, rid in self._jobs:
            self._spawn(c, rid)
        # queueing tasks may still be spawning judges — wait for them
        # first, then for every judge task
        await asyncio.gather(*self._queue_tasks)
        await asyncio.gather(*self._judge_tasks)
        checks = [self._out[(c.id, rid)] for c, rid in self._jobs]
        findings = _support_findings(self._parsed, self._jobs, checks)
        if self._own_http:
            await self._http.aclose()
        return claims, checks, findings


async def run_support(
    parsed: ParsedDocument,
    ref_checks: list[RefCheck],
    *,
    cache: Cache | None = None,
    http: httpx.AsyncClient | None = None,
) -> tuple[list[Claim], list[SupportCheck], list[Finding]]:
    run = SupportRun(parsed, cache=cache, http=http)
    for rc in ref_checks:
        run.add_check(rc)
    return await run.finish()


def _support_findings(
    parsed: ParsedDocument,
    jobs: list[tuple[Claim, str]],
    checks: list[SupportCheck],
) -> list[Finding]:
    ref_para = {r.id: r.paragraph_id for r in parsed.references}
    para_len = {p.id: len(p.text) for p in parsed.paragraphs}
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
    return findings


_POSITIVE = {"supported", "partial", "unsupported"}
_ESCALATE = {"partial", "unsupported"}


def _apply_verdict(
    out: JudgeOut, excerpt: str
) -> tuple[str, str | None, str, tuple[int, int] | None]:
    """§5.3 verification of one judge verdict.
    Returns (label, evidence, rationale, span)."""
    label, evidence, rationale = out.label, out.evidence, out.rationale
    if label not in _POSITIVE:
        return label, evidence, rationale, None
    if not evidence or not evidence.strip():
        return "undetermined", None, "模型未给出原文证据", None
    span = locate_evidence(evidence, excerpt)
    if span is None:
        return "undetermined", None, "证据未能在原文中定位", None
    return label, evidence, rationale, span


async def evaluate_with_excerpt(
    claim: Claim, ref_id: str, excerpt: str, title: str | None, source_kind: str
) -> SupportCheck:
    """Judge + §5.3 evidence verification on a ready excerpt.

    First pass uses task 'judge'. A verdict that survives verification as
    partial/unsupported is escalated to the 'review' model (same prompt,
    same §5.3 check); on review API failure it retries once via the
    'review_fallback' model, and if that fails too the first-pass
    verified result stands.
    """
    out = await judge_claim(
        claim.text, title, excerpt, sentence=claim.sentence
    )
    if out is None:
        return SupportCheck(
            claim_id=claim.id, ref_id=ref_id, label="undetermined",
            evidence=None, source_kind=source_kind,  # type: ignore[arg-type]
            rationale="模型输出无效，未作判断",
            source_title=title, source_excerpt=excerpt,
        )
    label, evidence, rationale, span = _apply_verdict(out, excerpt)
    if rationale == "证据未能在原文中定位":
        # exactly one re-ask: the model must copy a contiguous span
        # verbatim or concede undetermined (§5.3 unchanged)
        out2 = await judge_claim(
            claim.text, title, excerpt,
            sentence=claim.sentence, correction=True,
        )
        if out2 is not None:
            label, evidence, rationale, span = _apply_verdict(out2, excerpt)
            if out2.label == "undetermined" and not out2.rationale:
                rationale = "证据未能在原文中定位"

    if label in _ESCALATE:
        rev = await judge_claim(
            claim.text, title, excerpt,
            sentence=claim.sentence, task="review",
        )
        if rev is None:
            rev = await judge_claim(
                claim.text, title, excerpt,
                sentence=claim.sentence, task="review_fallback",
            )
        if rev is None:
            log.warning(
                "review cascade failed for claim %s; keeping first-pass %s",
                claim.id, label,
            )
        else:
            label, evidence, rationale, span = _apply_verdict(rev, excerpt)

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
