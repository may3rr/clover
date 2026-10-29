"""任务编排：解析 -> 四个图层并发 -> Report。

并发结构：[norms（含 typos + reorder）]、[authenticity -> support]、
[distribution]、[overview 准备：目标期刊参照论文 + 结构画像]；四层结束后
overview 的评审者汇总给出整体定位（可选，venue_id 为 None 时关闭）。每个图层单独包裹：单层异常只把该层标为 failed，其余
图层照常产出。authenticity 失败时 support 仍然运行（matched 为空，
全部 undetermined / source_kind=none）。

emit(dict) 回调收到 {type:"layer", layer, status, findings, anchors}
事件与 {type:"progress", layer, frac, label} 进度事件；解析成功后先发 {type:"parsed", outline}（前端骨架图用）；结束
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
from .lint.attribution import check_attribution
from .lint.norms import check_norms
from .lint.reorder import plan_reorder
from .distribution.registry import builtin_baseline, detect_from_manuscript, find_venue
from .config import venue_model_enabled
from .distribution.venue import MIN_EXEMPLARS
from .distribution.venue_metrics import prepare_venue
from .library.venue_match import paper_type
from .library import build_library, scan_folder
from .lint.venue_rules import check_venue_rules
from .lint.typos import check_typos
from .llm.client import doc_scope, stats_scope
from .parse.bibguess import guess_bibliography_start
from .parse import ParsedDocument, apply_bibliography_start, parse_document
from .parse.parser import relink_markers
from .refs.structure import structure_references
from .refs.sources import RetrievalClient
from .refs.verify import verify_references
from .schema import (
    Finding,
    LayerStatus,
    LibraryLink,
    LLMCalls,
    Overview,
    Report,
    ReportMeta,
    Revision,
)
from .overview.run import Prepared, critique, prepare, run_overview_safe
from .overview.venues import VENUES
from .support.layer import SupportRun

log = logging.getLogger(__name__)

LAYER_ORDER = ["authenticity", "support", "distribution", "norms"]

PARSE_ERROR = ("无法读取这个文件。请拖入 .docx 文件，或 LaTeX 项目的 .zip"
               " 压缩包、文件夹、主 .tex 文件。")


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
        if p.cell is None:  # the skeleton draws prose lines, not table grids
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
    library_dir: str | Path | None = None,
    library_links: list[LibraryLink] | None = None,
    library_venue: str | None = None,
    library_exemplars: list[str] | None = None,
    on_report: Callable[[Report], None] | None = None,
) -> Report:
    """on_report 不为空时，期刊对标不再卡住报告：四层结束就组装报告
    （overview 为 pending）交给 on_report 并发出 done（带 overview=pending），
    之后在同一个任务里继续算对标，完成后原地更新同一个 Report 对象，
    发 overview 与 overview_done 事件，再返回。"""
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
    progress_at: dict[str, float] = {}

    def _progress(layer: str, frac: float, label: str) -> None:
        """{type:"progress"} events for the running screen's bars; at most
        one per layer every 0.25s, except the final one."""
        now = time.monotonic()
        if frac < 1 and now - progress_at.get(layer, 0.0) < 0.25:
            return
        progress_at[layer] = now
        send({"type": "progress", "layer": layer,
              "frac": round(min(max(frac, 0.0), 1.0), 3), "label": label})

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

    # ---- parse (threaded; docx XML / latex source work) ----------------
    try:
        parsed = await asyncio.to_thread(parse_document, path)
    except Exception as e:
        log.warning("parse failed for %s: %s", path, e)
        for layer in LAYER_ORDER:
            _layer(layer, "failed")
        send({"type": "failed", "error": PARSE_ERROR})
        raise PipelineError(PARSE_ERROR) from e

    # last resort for the bibliography: no heading, no ZOTERO_BIBL field,
    # no trailing numbered run -> ask the cheap model where the list
    # starts and accept only a deterministically-verifiable span (T1e)
    if (not parsed.references and parsed.paragraphs
            and parsed.document.source_format == "docx"):
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

        async def _structure() -> None:
            # every entry is re-structured by the model (regex can be
            # confidently wrong on unfamiliar styles); fields must be
            # grounded in the entry text. .bib-derived LaTeX entries are
            # already structured data. Runs concurrently with the work
            # that doesn't read reference fields (typos, claim extraction);
            # authenticity, distribution and claim->ref pairing wait for it.
            if not parsed.references:
                return
            done = set(parsed.structured_refs)
            try:
                changed = await structure_references(
                    [r for r in parsed.references
                     if r.origin == "list" and r.id not in done],
                    progress=lambda d, t: _progress(
                        "authenticity", 0.15 * d / max(t, 1),
                        f"整理参考文献 {d}/{t} 批"))
            except Exception as e:  # noqa: BLE001 — regex fields stand
                log.warning("reference structuring failed: %s", e)
                changed = 0
            if changed:
                relink_markers(parsed)
                log.info("model re-structured %d references; markers "
                         "relinked", changed)

        structured = asyncio.create_task(_structure())

        async def _library():
            # the folder scan (pypdf, threaded) overlaps structuring; the
            # link step needs the structured titles and authors
            if not library_dir:
                return None, {}, []
            try:
                pdfs = await asyncio.to_thread(
                    scan_folder, library_dir, cache,
                    lambda d, t: _progress(
                        "authenticity", 0.15 * d / max(t, 1),
                        f"读取文献文件夹 {d}/{t} 篇"))
                await structured
                trace = detect_from_manuscript(parsed)
                lib, local, pdfs = await build_library(
                    parsed.references, library_dir, links=library_links,
                    venue=library_venue, cache=cache, pdfs=pdfs,
                    exemplar_ids=library_exemplars,
                    fallback_venue=trace["name"] if trace else None,
                    manuscript_type=paper_type(parsed.document.title))
            except Exception as e:  # noqa: BLE001 — the run goes on without it
                log.warning("reference library failed: %s", e)
                return None, {}, []
            send({"type": "library", "linked": len(lib.links),
                  "docs": len(lib.docs), "exemplars": len(lib.exemplar_ids)})
            return lib, local, pdfs

        library_task = asyncio.create_task(_library())

        async def _venue():
            """(registry entry or None, name, benchmark dict or None,
            source, VenueContext or None): the target journal and the
            baseline to compare against — exemplars from the folder
            first, the built-in baseline next, the default benchmark
            otherwise (distribution falls back)."""
            lib, _local, pdfs = await library_task
            await structured
            entry = (find_venue(library_venue) or find_venue(lib.venue if lib else None)
                     or detect_from_manuscript(parsed))
            name = library_venue or (lib.venue if lib else None) or (
                entry["name"] if entry else None)
            if lib and len(lib.exemplar_ids) >= MIN_EXEMPLARS:
                by_id = {p.doc.id: p for p in pdfs}
                ex = [by_id[i] for i in lib.exemplar_ids if i in by_id]
                try:
                    bench, ctx = await prepare_venue(
                        ex, name or "目标期刊", parsed, cache,
                        use_model=venue_model_enabled())
                except Exception as e:  # noqa: BLE001
                    log.warning("venue benchmark failed: %s", e)
                    bench, ctx = None, None
                if bench is not None:
                    return entry, name or "目标期刊", bench, "exemplars", ctx
            bench = builtin_baseline(entry)
            return entry, name, bench, "builtin" if bench else None, None

        venue_task = asyncio.create_task(_venue())
        # let the structuring batches reach the cloud semaphore before the
        # layers queue their calls: priority orders waiters, but cannot
        # take back a slot already handed to a claim-extraction call
        for _ in range(3):
            await asyncio.sleep(0)
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
                    parsed, cache=cache, http=retrieval._client,
                    refs_ready=structured,
                    progress=lambda f, lb: _progress("support", f, lb))
                _lib, local, _pdfs = await library_task
                sup.set_local(local)
                n_refs = len(parsed.references)
                n_checked = 0

                def on_ref(check):
                    nonlocal n_checked
                    n_checked += 1
                    _progress("authenticity",
                              0.15 + 0.85 * n_checked / max(n_refs, 1),
                              f"核验参考文献 {n_checked}/{n_refs} 篇")
                    return sup.add_check(check)
                _layer("authenticity", "running")
                await structured
                try:
                    auth_checks, auth_findings = await verify_references(
                        parsed.references, parsed.paragraphs, retrieval,
                        on_ref=on_ref, local=local)
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
                await structured
                _entry, vname, vbench, vsource, vctx = await venue_task
                try:
                    dist, dist_findings = await run_distribution(
                        parsed, bench_path=benchmark_path(benchmark_id),
                        bench=vbench, venue=vname, venue_source=vsource,
                        venue_ctx=vctx,
                        progress=lambda d, t: _progress(
                            "distribution", d / max(t, 1),
                            f"分类引用功能 {d}/{t} 段"))
                except Exception as e:  # noqa: BLE001
                    log.warning("distribution layer failed: %s", e)
                    _layer("distribution", "failed", error=_short_error(e))
                    return
                _layer("distribution", "done", len(dist_findings),
                       anchors=_anchors(dist_findings))

            async def _norms() -> None:
                nonlocal norm_findings, revisions
                _layer("norms", "running")
                # typos read paragraph text only — no need to wait for
                # reference structuring
                typo_task = asyncio.create_task(check_typos(
                    parsed, progress=lambda d, t: _progress(
                        "norms", d / max(t, 1), f"检查错别字 {d}/{t} 段")))
                try:
                    await structured
                    norm_findings = check_norms(parsed)
                    norm_findings += check_attribution(parsed)
                    entry = (await venue_task)[0]
                    if entry is not None:
                        norm_findings += check_venue_rules(parsed, entry)
                    typo_findings, typo_revs = await typo_task
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
            async def _prep():
                await structured
                return await prepare(
                    parsed, venue_id, retrieval._client, cache,
                    on_step=lambda step: send(
                        {"type": "overview", "status": "running",
                         "step": step}))

            prep_task = asyncio.create_task(run_overview_safe(_prep())) \
                if venue_id else None

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
            if parsed.latex is not None:
                from .parse.latex.locate import annotate_locations
                annotate_locations(
                    parsed.latex,
                    [f.anchor for f in findings] +
                    [r.anchor for r in revisions])
            for i, r in enumerate(revisions, 1):
                r.id = f"v{i}"

            overview = None
            t_ov = time.monotonic()
            defer = prep_task is not None and on_report is not None

            async def _finish_overview() -> Overview | None:
                send({"type": "overview", "status": "running"})
                prep = await prep_task
                ov = None
                if isinstance(prep, Prepared):
                    send({"type": "overview", "status": "running",
                          "step": "正在汇总评审意见"})
                    ov = await run_overview_safe(critique(prep, findings))
                send({"type": "overview",
                      "status": ov.status if ov else "unavailable"})
                return ov

            if defer:
                overview = Overview(
                    status="pending", venue_id=venue_id,
                    venue_name=VENUES[venue_id].name
                    if venue_id in VENUES else venue_id)
            elif prep_task is not None:
                overview = await _finish_overview()

            meta.llm_calls = LLMCalls(local=stats.local, cloud=stats.cloud)
            meta.duration_s = round(time.monotonic() - t0, 1)
            meta.token_usage = {m: dict(u) for m, u in stats.usage.items()}
            meta.timings = {
                "parse": round(t_parsed - t0, 1),
                "layers": layer_times,
                # 四层结束后等待期刊对标的时长（未开启对标时为 0）
                "overview": round(time.monotonic() - t_ov, 1),
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
                library=(await library_task)[0],
                meta=meta,
            )
            if not defer:
                send({"type": "done"})
                return report

            # 报告先开：此刻对标还在算，前端凭 overview=pending 保持订阅
            on_report(report)
            send({"type": "done", "overview": "pending"})
            try:
                report.overview = await _finish_overview()
            except Exception as e:  # noqa: BLE001
                log.warning("deferred overview failed: %s", e)
                send({"type": "overview", "status": "unavailable"})
                report.overview = None
            report.meta.timings["overview"] = round(time.monotonic() - t_ov, 1)
            report.meta.duration_s = round(time.monotonic() - t0, 1)
            send({"type": "overview_done"})
            return report
        finally:
            if own_retrieval:
                await retrieval.close()
