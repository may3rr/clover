"""任务编排：解析 -> 四个图层并发 -> Report。

并发结构：[norms（含 typos + reorder）]、[authenticity -> support]、
[distribution]、[overview 准备：目标期刊参照论文 + 结构画像]；四层结束后
overview 的评审者汇总给出整体定位（可选，venue_id 为 None 时关闭）。每个图层单独包裹：单层异常只把该层标为 failed，其余
图层照常产出。authenticity 失败时 support 仍然运行（matched 为空，
全部 undetermined / source_kind=none）。

emit(dict) 回调收到 {type:"layer", layer, status, findings, anchors}
事件；解析成功后先发 {type:"parsed", outline}（前端骨架图用）；结束
时 {type:"done"}，或解析失败 / 致命错误时 {type:"failed", error}。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from .cache import Cache
from .config import get_settings
from .distribution.bench import _DEFAULT as _DEFAULT_BENCH
from .distribution.layer import run_distribution
from .lint.norms import check_norms
from .lint.reorder import plan_reorder
from .lint.typos import check_typos
from .llm.client import doc_scope, stats_scope
from .parse.bibguess import guess_bibliography_start
from .parse.parser import ParsedDocument, apply_bibliography_start, parse_docx
from .refs.sources import RetrievalClient
from .refs.verify import verify_references
from .schema import (
    Finding,
    LayerStatus,
    LLMCalls,
    Report,
    ReportMeta,
    Revision,
)
from .overview.run import Prepared, critique, prepare, run_overview_safe
from .support.layer import SupportRun

log = logging.getLogger(__name__)

LAYER_ORDER = ["authenticity", "support", "distribution", "norms"]

PARSE_ERROR = "无法读取这个文件。请确认它是 .docx 格式，然后重新拖入。"


class PipelineError(Exception):
    """Fatal pipeline failure carrying a user-facing Chinese message."""


def _short_error(e: BaseException) -> str:
    msg = str(e).strip().splitlines()
    return (msg[0][:120] if msg and msg[0] else type(e).__name__) or "未知错误"


def benchmark_path(benchmark_id: str) -> Path:
    return _DEFAULT_BENCH.parent / f"{benchmark_id}.json"


def _outline(parsed: ParsedDocument) -> dict:
    """Document outline for the running-screen skeleton: section headings,
    paragraph lengths and citation-marker positions (relative 0..1)."""
    markers_by_para: dict[str, list[float]] = {}
    para_len = {p.id: max(len(p.text), 1) for p in parsed.paragraphs}
    for m in parsed.markers:
        markers_by_para.setdefault(m.paragraph_id, []).append(
            round(m.start / para_len.get(m.paragraph_id, 1), 4))
    paras_by_section: dict[str, list] = {}
    for p in parsed.paragraphs:
        paras_by_section.setdefault(p.section_id, []).append(p)
    heading_ids = {s.heading_paragraph_id for s in parsed.sections}
    return {
        "title": parsed.document.title,
        "sections": [
            {
                "id": s.id,
                "title": s.title,
                "canonical": s.canonical,
                # heading paragraphs stay in the list (flagged) so layer
                # anchors pointing at a section heading still resolve
                "paragraphs": [
                    {
                        "id": p.id,
                        "length": len(p.text),
                        "markers": markers_by_para.get(p.id, []),
                        "heading": p.id in heading_ids,
                    }
                    for p in paras_by_section.get(s.id, [])
                ],
            }
            for s in parsed.sections
        ],
        "references": len(parsed.references),
    }


async def run_pipeline(
    path: str | Path,
    benchmark_id: str = "arxiv_cs_cl",
    emit: Callable[[dict], None] | None = None,
    *,
    retrieval: RetrievalClient | None = None,
    cache: Cache | None = None,
    venue_id: str | None = None,
) -> Report:
    send = emit or (lambda _e: None)
    t0 = time.monotonic()
    meta = ReportMeta()
    meta.layers = {k: LayerStatus() for k in LAYER_ORDER}

    def _anchors(findings: list[Finding]) -> list[dict]:
        out = []
        for f in findings:
            if f.anchor is None:
                continue
            p = para_by_id.get(f.anchor.paragraph_id)
            n = max(len(p.text), 1) if p else 1
            out.append({
                "paragraph_id": f.anchor.paragraph_id,
                "start_rel": round(min(f.anchor.start, n) / n, 4),
                "end_rel": round(min(f.anchor.end, n) / n, 4),
                "severity": f.severity,
            })
        return out

    layer_start: dict[str, float] = {}
    layer_times: dict[str, float] = {}

    def _layer(layer: str, status: str, n: int = 0, error: str | None = None,
               anchors: list[dict] | None = None):
        if status == "running":
            layer_start[layer] = time.monotonic()
        elif layer in layer_start:
            layer_times[layer] = round(
                time.monotonic() - layer_start[layer], 1)
        meta.layers[layer].status = status  # type: ignore[assignment]
        meta.layers[layer].findings = n
        meta.layers[layer].error = error
        ev = {"type": "layer", "layer": layer, "status": status,
              "findings": n}
        if error:
            ev["error"] = error
        if anchors:
            ev["anchors"] = anchors
        send(ev)

    # ---- parse (threaded; docx XML work) -------------------------------
    try:
        parsed = await asyncio.to_thread(parse_docx, path)
    except Exception as e:
        log.warning("parse failed for %s: %s", path, e)
        for layer in LAYER_ORDER:
            _layer(layer, "failed")
        send({"type": "failed", "error": PARSE_ERROR})
        raise PipelineError(PARSE_ERROR) from e

    # last resort for the bibliography: no heading, no ZOTERO_BIBL field,
    # no trailing numbered run -> ask the cheap model where the list
    # starts and accept only a deterministically-verifiable span (T1e)
    if not parsed.references and parsed.paragraphs:
        try:
            start = await guess_bibliography_start(parsed)
        except Exception as e:  # noqa: BLE001 — guessing is optional
            log.warning("bibliography boundary guess failed: %s", e)
            start = None
        if start is not None:
            added = await asyncio.to_thread(
                apply_bibliography_start, parsed, start)
            log.info("llm bibliography boundary -> %d references", added)

    para_by_id = {p.id: p for p in parsed.paragraphs}
    t_parsed = time.monotonic()
    send({"type": "parsed", "outline": _outline(parsed)})

    # uploaded files are stored as "<hex>_<name>.docx" — strip the prefix
    # so usage rows show the document's real name
    doc_label = (parsed.document.filename or
                 re.sub(r"^[0-9a-f]{16}_", "", Path(path).name))
    with stats_scope() as stats, doc_scope(doc_label):
        own_retrieval = retrieval is None
        cache = cache or Cache(get_settings().cache_path)
        retrieval = retrieval or RetrievalClient(cache=cache)
        try:
            auth_checks, auth_findings = [], []
            claims, support_checks, sup_findings = [], [], []
            dist = None
            norm_findings: list[Finding] = []
            revisions: list[Revision] = []
            dist_findings: list[Finding] = []

            async def _auth_then_support() -> None:
                nonlocal auth_checks, auth_findings
                nonlocal claims, support_checks, sup_findings
                # claims extraction (LLM) doesn't need verification — it
                # starts immediately; each ref's judge pairs queue as its
                # RefCheck lands (on_ref), overlapping auth and support.
                _layer("support", "running")
                sup = SupportRun(
                    parsed, cache=cache, http=retrieval._client)
                _layer("authenticity", "running")
                try:
                    auth_checks, auth_findings = await verify_references(
                        parsed.references, parsed.paragraphs, retrieval,
                        on_ref=sup.add_check)
                except Exception as e:  # noqa: BLE001
                    log.warning("authenticity layer failed: %s", e)
                    _layer("authenticity", "failed", error=_short_error(e))
                else:
                    _layer("authenticity", "done", len(auth_findings),
                           anchors=_anchors(auth_findings))
                try:
                    # support finishes even when authenticity failed
                    # (no checks -> every pair undetermined, none source)
                    claims, support_checks, sup_findings = await sup.finish()
                except Exception as e:  # noqa: BLE001
                    log.warning("support layer failed: %s", e)
                    _layer("support", "failed", error=_short_error(e))
                    return
                _layer("support", "done", len(sup_findings),
                       anchors=_anchors(sup_findings))

            async def _distribution() -> None:
                nonlocal dist, dist_findings
                _layer("distribution", "running")
                try:
                    dist, dist_findings = await run_distribution(
                        parsed, bench_path=benchmark_path(benchmark_id))
                except Exception as e:  # noqa: BLE001
                    log.warning("distribution layer failed: %s", e)
                    _layer("distribution", "failed", error=_short_error(e))
                    return
                _layer("distribution", "done", len(dist_findings),
                       anchors=_anchors(dist_findings))

            async def _norms() -> None:
                nonlocal norm_findings, revisions
                _layer("norms", "running")
                try:
                    norm_findings = check_norms(parsed)
                    typo_findings, typo_revs = await check_typos(parsed)
                    norm_findings += typo_findings
                    reorder_revs = await asyncio.to_thread(plan_reorder, parsed)
                    revisions = typo_revs + reorder_revs
                except Exception as e:  # noqa: BLE001
                    log.warning("norms layer failed: %s", e)
                    _layer("norms", "failed", error=_short_error(e))
                    return
                _layer("norms", "done", len(norm_findings),
                       anchors=_anchors(norm_findings))

            # overview prep (venue exemplars + shape reading) needs no
            # findings — it overlaps the four layers
            prep_task = asyncio.create_task(run_overview_safe(
                prepare(parsed, venue_id, retrieval._client, cache))
            ) if venue_id else None

            await asyncio.gather(
                _auth_then_support(), _distribution(), _norms())

            findings = norm_findings + auth_findings + sup_findings + dist_findings
            para_pos = {p.id: i for i, p in enumerate(parsed.paragraphs)}
            findings.sort(key=lambda f: (
                0 if f.anchor is None else 1,
                para_pos.get(f.anchor.paragraph_id, 0) if f.anchor else 0,
                f.anchor.start if f.anchor else 0,
            ))
            for i, f in enumerate(findings, 1):
                f.id = f"f{i}"
            for i, r in enumerate(revisions, 1):
                r.id = f"v{i}"

            overview = None
            if prep_task is not None:
                send({"type": "overview", "status": "running"})
                prep = await prep_task
                if isinstance(prep, Prepared):
                    overview = await run_overview_safe(critique(prep, findings))
                send({"type": "overview",
                      "status": overview.status if overview else "unavailable"})

            meta.llm_calls = LLMCalls(local=stats.local, cloud=stats.cloud)
            meta.duration_s = round(time.monotonic() - t0, 1)
            meta.token_usage = {m: dict(u) for m, u in stats.usage.items()}
            meta.timings = {
                "parse": round(t_parsed - t0, 1),
                "layers": layer_times,
                "sources": {
                    k: dict(v)
                    for k, v in getattr(retrieval, "stats", {}).items()
                },
            }

            report = Report(
                document=parsed.document,
                sections=parsed.sections,
                paragraphs=parsed.paragraphs,
                markers=parsed.markers,
                references=parsed.references,
                ref_checks=auth_checks,
                claims=claims,
                support_checks=support_checks,
                distribution=dist,
                findings=findings,
                revisions=revisions,
                overview=overview,
                meta=meta,
            )
            send({"type": "done"})
            return report
        finally:
            if own_retrieval:
                await retrieval.close()
