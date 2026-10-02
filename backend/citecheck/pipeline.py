"""任务编排：解析 -> 四个图层并发 -> Report。

并发结构：[norms（含 typos + reorder）]、[authenticity -> support]、
[distribution]。每个图层单独包裹：单层异常只把该层标为 failed，其余
图层照常产出。authenticity 失败时 support 仍然运行（matched 为空，
全部 undetermined / source_kind=none）。

emit(dict) 回调收到 {type:"layer", layer, status, findings} 事件；结束
时 {type:"done"}，或解析失败 / 致命错误时 {type:"failed", error}。
"""

from __future__ import annotations

import asyncio
import logging
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
from .llm.client import stats_scope
from .parse.parser import ParsedDocument, parse_docx
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
from .support.layer import run_support

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


async def run_pipeline(
    path: str | Path,
    benchmark_id: str = "arxiv_cs_cl",
    emit: Callable[[dict], None] | None = None,
    *,
    retrieval: RetrievalClient | None = None,
    cache: Cache | None = None,
) -> Report:
    send = emit or (lambda _e: None)
    t0 = time.monotonic()
    meta = ReportMeta()
    meta.layers = {k: LayerStatus() for k in LAYER_ORDER}

    def _layer(layer: str, status: str, n: int = 0, error: str | None = None):
        meta.layers[layer].status = status  # type: ignore[assignment]
        meta.layers[layer].findings = n
        meta.layers[layer].error = error
        ev = {"type": "layer", "layer": layer, "status": status,
              "findings": n}
        if error:
            ev["error"] = error
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

    with stats_scope() as stats:
        own_retrieval = retrieval is None
        retrieval = retrieval or RetrievalClient(cache=cache)
        try:
            auth_checks, auth_findings = [], []
            claims, support_checks, sup_findings = [], [], []
            dist = None
            norm_findings: list[Finding] = []
            revisions: list[Revision] = []
            dist_findings: list[Finding] = []

            async def _authenticity() -> None:
                nonlocal auth_checks, auth_findings
                _layer("authenticity", "running")
                try:
                    auth_checks, auth_findings = await verify_references(
                        parsed.references, parsed.paragraphs, retrieval)
                except Exception as e:  # noqa: BLE001
                    log.warning("authenticity layer failed: %s", e)
                    _layer("authenticity", "failed", error=_short_error(e))
                    return
                _layer("authenticity", "done", len(auth_findings))

            async def _support() -> None:
                nonlocal claims, support_checks, sup_findings
                _layer("support", "running")
                try:
                    claims, support_checks, sup_findings = await run_support(
                        parsed, auth_checks,
                        cache=cache, http=retrieval._client)
                except Exception as e:  # noqa: BLE001
                    log.warning("support layer failed: %s", e)
                    _layer("support", "failed", error=_short_error(e))
                    return
                _layer("support", "done", len(sup_findings))

            async def _auth_then_support() -> None:
                await _authenticity()
                # support runs even when authenticity failed (checks=[] ->
                # every pair undetermined with source_kind=none)
                await _support()

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
                _layer("distribution", "done", len(dist_findings))

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
                _layer("norms", "done", len(norm_findings))

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

            meta.llm_calls = LLMCalls(local=stats.local, cloud=stats.cloud)
            meta.duration_s = round(time.monotonic() - t0, 1)
            meta.token_usage = {m: dict(u) for m, u in stats.usage.items()}

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
                meta=meta,
            )
            send({"type": "done"})
            return report
        finally:
            if own_retrieval:
                await retrieval.close()
