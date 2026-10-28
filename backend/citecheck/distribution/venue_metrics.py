"""期刊对标的细化指标：稿件与每篇范文逐项比较，可追溯到页码与段落。

``prepare_venue`` turns the selected exemplar PDFs into a benchmark
(profiles, optional model reads, heading types fixed by the model) and a
``VenueContext``; the distribution layer then calls ``compare`` with the
manuscript's own numbers. Every metric lists each exemplar's value with
the page and the line it was read from, and the manuscript paragraphs
behind the manuscript's value.

Out-of-range measures become one low-severity finding per group, worded
as a reference point for the author: no rewriting, no suggestion of
what to cite (AGENTS §2).
"""

from __future__ import annotations

import asyncio
import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import date

from ..library.scan import LocalPdf
from ..library.venue_match import paper_type
from ..parse.headings import is_back_matter, is_ref_heading
from ..parse.parser import ParsedDocument
from ..schema import (Anchor, ExemplarInfo, ExemplarValue, Finding, SectionDist, Stat,
                      VenueMetric)
from ..support.evidence import locate_evidence
from .venue import (MIN_EXEMPLARS, REF_TYPES, aggregate, load_profiles, manuscript_abstract,
                    manuscript_stats, ref_type)

log = logging.getLogger(__name__)

CANON_ZH = {"intro": "引言", "related": "相关研究", "method": "方法", "experiment": "实验",
            "discussion": "讨论", "conclusion": "结论"}
TYPE_ZH = {"journal": "期刊论文", "conference": "会议论文", "preprint": "预印本",
           "book": "图书", "thesis": "学位论文", "web": "网络资源"}
FUNC_ZH = {"background": "背景", "method": "方法", "comparison": "对比", "result": "结果",
           "critique": "批评"}
GROUP_TITLE = {
    "structure": "章节结构",
    "distribution": "引用位置",
    "references": "参考文献构成",
    "functions": "引用功能构成",
    "elements": "研究要素",
    "length": "篇幅与图表",
}
_MAX_ANCHORS = 12
_CJK = re.compile(r"[一-鿿]")


@dataclass
class Exemplar:
    pdf: LocalPdf
    prof: dict | None
    model: dict | None = None
    similar: bool = False


@dataclass
class VenueContext:
    venue: str
    exemplars: list[Exemplar]
    # heading title -> canonical, from the model, both sides
    overrides: dict[str, str] = field(default_factory=dict)
    # manuscript research elements (model) and the text they were read from
    elements: dict[str, dict] | None = None
    elements_text: str = ""

    @property
    def used(self) -> list[Exemplar]:
        return [e for e in self.exemplars if e.prof]


# ------------------------------------------------------------ preparation


def _tokens(text: str) -> list[str]:
    text = (text or "").lower()
    cjk = re.findall(r"[一-鿿]+", text)
    return re.findall(r"[a-z0-9]+", text) + [s[i:i + 2] for s in cjk for i in range(len(s) - 1)]


def _mark_similar(parsed: ParsedDocument, items: list[Exemplar], k: int = 3) -> None:
    from rank_bm25 import BM25Okapi

    used = [e for e in items if e.prof]
    q = _tokens(f"{parsed.document.title or ''} {manuscript_abstract(parsed) or ''}")
    if not used or not q:
        return
    docs = [_tokens(f"{e.prof.get('title') or ''} " * 2 + (e.prof.get("abstract") or ""))
            for e in used]
    if not any(docs):
        return
    scores = BM25Okapi([d or ["_"] for d in docs]).get_scores(q)
    for i in sorted(range(len(used)), key=lambda i: -scores[i])[:k]:
        if scores[i] > 0:
            used[i].similar = True


def apply_overrides(prof: dict, overrides: dict[str, str]) -> dict:
    """The profile with model-typed headings regrouped by canonical."""
    if not overrides:
        return prof
    heads = [{**h, "canonical": overrides.get(h["title"], h["canonical"])
              if h["canonical"] == "other" else h["canonical"]} for h in prof["headings"]]
    sections: dict[str, dict] = {}
    for h in heads:
        s = sections.setdefault(h["canonical"], {"cites": 0, "words": 0, "markers": 0,
                                                 "page": h["page"], "title": h["title"]})
        for k in ("cites", "words", "markers"):
            s[k] += h.get(k, 0)
    return {**prof, "headings": heads, "sections": sections}


async def prepare_venue(exemplars: list[LocalPdf], venue: str, parsed: ParsedDocument,
                        cache=None, *, use_model: bool = False
                        ) -> tuple[dict | None, VenueContext | None]:
    """(benchmark, context) from the selected exemplars, (None, None)
    with fewer than MIN_EXEMPLARS readable ones."""
    pairs = await asyncio.to_thread(load_profiles, exemplars, cache)
    items = [Exemplar(pdf, prof) for pdf, prof in pairs]
    used = [e for e in items if e.prof]
    if len(used) < MIN_EXEMPLARS:
        return None, None
    ctx = VenueContext(venue=venue, exemplars=items)
    if use_model:
        from . import venue_model as vm

        titles = [h["title"] for e in used for h in e.prof["headings"]]
        titles += [s.title for s in parsed.sections if s.canonical == "other" and s.title]
        parts, ctx.elements_text = vm.manuscript_parts(parsed)
        overrides, ms_elements, *reads = await asyncio.gather(
            vm.classify_headings(titles), vm.read_elements(parts, ctx.elements_text),
            *(vm.enrich(e.prof) for e in used), return_exceptions=True)
        ctx.overrides = overrides if isinstance(overrides, dict) else {}
        ctx.elements = ms_elements if isinstance(ms_elements, dict) else None
        for e, r in zip(used, reads):
            e.model = r if isinstance(r, dict) else None
        for e in used:
            e.prof = apply_overrides(e.prof, ctx.overrides)
    _mark_similar(parsed, items)
    return aggregate([e.prof for e in used], venue), ctx


def section_overrides(parsed: ParsedDocument, ctx: VenueContext | None) -> dict[str, str]:
    """section_id -> canonical for manuscript sections the model typed."""
    if not ctx or not ctx.overrides:
        return {}
    return {s.id: ctx.overrides[s.title] for s in parsed.sections
            if s.canonical == "other" and s.title in ctx.overrides}


# ------------------------------------------------------------- comparison


def _q(vals: list[float]) -> Stat | None:
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return None
    q1, med, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    if q3 - q1 <= 0:
        return None
    return Stat(median=med, q1=q1, q3=q3)


def _flag(value: float | None, st: Stat | None) -> str:
    if value is None or st is None:
        return "na"
    return "below" if value < st.q1 else "above" if value > st.q3 else "within"


def _para_anchor(parsed: ParsedDocument, pid: str | None) -> Anchor | None:
    if not pid:
        return None
    p = next((x for x in parsed.paragraphs if x.id == pid), None)
    return Anchor(paragraph_id=pid, start=0, end=len(p.text)) if p else None


def _quote_anchor(parsed: ParsedDocument, quote: str | None) -> Anchor | None:
    if not quote:
        return None
    for p in parsed.paragraphs:
        span = locate_evidence(quote, p.text)
        if span:
            return Anchor(paragraph_id=p.id, start=span[0], end=span[1])
    return None


def _quote_page(prof: dict, quote: str | None) -> int | None:
    if not quote:
        return None
    if prof.get("abstract") and locate_evidence(quote, prof["abstract"]):
        return prof.get("abstract_page")
    for h in prof.get("headings", []):
        if locate_evidence(quote, h["title"]):
            return h["page"]
    for c in prof.get("captions", []):
        if locate_evidence(quote, c["text"]):
            return c["page"]
    return None


def _body_sections(parsed: ParsedDocument, canon: dict[str, str]):
    secs = parsed.sections
    start = next((i for i, s in enumerate(secs) if canon[s.id] != "other"), None)
    if start is None:
        return []
    out = []
    for s in secs[start:]:
        if is_ref_heading(s.title) or is_back_matter(s.title + "：") or s.title.startswith(("作者贡献", "利益冲突", "致谢", "附录")):
            break
        out.append(s)
    return out


@dataclass
class _Spec:
    key: str
    group: str
    label: str
    unit: str
    kind: str = "number"


def _ex_values(e: Exemplar) -> dict[str, tuple[float | None, int | None, str | None]]:
    """key -> (value, page, quote) for one exemplar."""
    p = e.prof
    out: dict[str, tuple[float | None, int | None, str | None]] = {}
    secs = p["sections"]
    words = p.get("words") or sum(s["words"] for s in secs.values()) or 0
    for c in CANON_ZH:
        s = secs.get(c)
        out[f"present:{c}"] = (1.0 if s else 0.0, s["page"] if s else None, s["title"] if s else None)
        if s:
            out[f"words:{c}"] = (s["words"] / words if words else None, s["page"], s["title"])
            out[f"share:{c}"] = (s["cites"] / p["total_cites"], s["page"], s["title"])
            out[f"density:{c}"] = (s["cites"] * 1000 / s["words"] if s["words"] else None,
                                   s["page"], s["title"])
        else:
            out[f"share:{c}"] = (0.0, None, None)
    sents = p.get("sentences", [])
    if sents:
        top = max(sents, key=lambda s: s["ids"])
        for k in (2, 5):
            out[f"sent_ge{k}"] = (sum(1 for s in sents if s["ids"] >= k) / len(sents),
                                  top["page"], top["text"][:80])
    vs = p["venue_stats"]
    rp = p.get("ref_page")
    out["n_refs"] = (vs["n_refs"], rp, None)
    out["recent_share"] = (vs["recent_share"], rp, None)
    out["foreign_share"] = (vs["foreign_share"], rp, None)
    years = p.get("ref_years") or []
    out["ref_age"] = (statistics.median([p["year"] - y for y in years]) if years else None, rp, None)
    types = p.get("ref_types") or []
    for t in REF_TYPES:
        out[f"type:{t}"] = (types.count(t) / len(types) if types else None, rp, None)
    out["words"] = (words, None, None)
    out["abstract_chars"] = (vs["abstract_chars"], p.get("abstract_page"), None)
    figs = [c for c in p.get("captions", []) if c["kind"] == "fig"]
    tabs = [c for c in p.get("captions", []) if c["kind"] == "tab"]
    out["n_figures"] = (vs["n_figures"], figs[-1]["page"] if figs else None,
                        figs[-1]["text"] if figs else None)
    out["n_tables"] = (vs["n_tables"], tabs[-1]["page"] if tabs else None,
                       tabs[-1]["text"] if tabs else None)
    if e.model:
        fn = e.model.get("functions") or {}
        total = sum(fn.values())
        for f in FUNC_ZH:
            out[f"func:{f}"] = (fn.get(f, 0) / total if total else None, None, None)
        for k, v in (e.model.get("elements") or {}).items():
            out[f"elem:{k}"] = (v["value"], _quote_page(p, v["quote"]), v["quote"])
    return out


def compare(parsed: ParsedDocument, ctx: VenueContext, *, dist_sections: list[SectionDist],
            canon: dict[str, str], citing_counts: list[int],
            marker_functions: dict[str, str] | None, comparable: bool,
            year: int | None = None) -> tuple[list[VenueMetric], list[Finding], list[ExemplarInfo]]:
    from .venue_model import ELEMENTS

    used = ctx.used
    n = len(used)
    ex_vals = {e.pdf.doc.id: _ex_values(e) for e in used}
    year = year or date.today().year

    # ---- the manuscript's values and the paragraphs behind them --------
    mine: dict[str, tuple[float | None, list[Anchor], str | None]] = {}
    body = _body_sections(parsed, canon)
    body_ids = {s.id for s in body}
    sec_rows = [sd for sd in dist_sections if sd.section_id in body_ids]
    words = sum(sd.words for sd in sec_rows)
    total = sum(sd.citations for sd in dist_sections)
    by_canon: dict[str, list[SectionDist]] = {}
    for sd in sec_rows:
        by_canon.setdefault(sd.canonical, []).append(sd)
    heading = {s.id: s.heading_paragraph_id for s in parsed.sections}
    for c in CANON_ZH:
        rows = by_canon.get(c, [])
        anchors = [a for sd in rows if (a := _para_anchor(parsed, heading.get(sd.section_id)))]
        mine[f"present:{c}"] = (1.0 if rows else 0.0, anchors, None)
        if rows:
            w = sum(sd.words for sd in rows)
            ci = sum(sd.citations for sd in rows)
            mine[f"words:{c}"] = (w / words if words else None, anchors, None)
            mine[f"share:{c}"] = (ci / total if total else None, anchors, None)
            mine[f"density:{c}"] = (ci * 1000 / w if w else None, anchors, None)
        else:
            mine[f"share:{c}"] = (0.0 if total else None, [], None)
    if citing_counts:
        for k in (2, 5):
            mine[f"sent_ge{k}"] = (sum(1 for x in citing_counts if x >= k) / len(citing_counts),
                                   [], None)
    refs = [r for r in parsed.references if r.origin == "list"]
    ms = manuscript_stats(parsed, year)
    ref_head = next((s.heading_paragraph_id for s in parsed.sections if is_ref_heading(s.title)), None)
    ra = [a] if (a := _para_anchor(parsed, ref_head)) else []
    mine["n_refs"] = (ms["n_refs"], ra, None)
    mine["recent_share"] = (ms["recent_share"], ra, None)
    mine["foreign_share"] = (ms["foreign_share"], ra, None)
    years = [r.year for r in refs if r.year]
    mine["ref_age"] = (statistics.median([year - y for y in years]) if years else None, ra, None)
    types = [ref_type(r.raw) for r in refs]
    for t in REF_TYPES:
        anchors = [a for r, rt in zip(refs, types) if rt == t
                   and (a := _para_anchor(parsed, r.paragraph_id))][:_MAX_ANCHORS]
        mine[f"type:{t}"] = (types.count(t) / len(types) if types else None, anchors, None)
    mine["words"] = (words or None, [], None)
    abstract_sec = next((s for s in parsed.sections if s.title.strip().rstrip(":：") == "摘要"), None)
    mine["abstract_chars"] = (ms["abstract_chars"],
                              [a] if abstract_sec and (a := _para_anchor(parsed, abstract_sec.heading_paragraph_id)) else [],
                              None)
    caps = [p for p in parsed.paragraphs if p.caption]
    for key, kw in (("n_figures", ("图", "fig")), ("n_tables", ("表", "tab"))):
        anchors = [a for p in caps if p.text.strip().lower().startswith(kw)
                   and (a := _para_anchor(parsed, p.id))][:_MAX_ANCHORS]
        mine[key] = (ms[key], anchors, None)
    if marker_functions:
        mk = {m.id: m for m in parsed.markers}
        tot = len(marker_functions)
        for f in FUNC_ZH:
            ids = [mid for mid, fn in marker_functions.items() if fn == f]
            anchors = [Anchor(paragraph_id=mk[i].paragraph_id, start=mk[i].start, end=mk[i].end)
                       for i in ids if i in mk][:_MAX_ANCHORS]
            mine[f"func:{f}"] = (len(ids) / tot if tot else None, anchors, None)
    if ctx.elements:
        for k, v in ctx.elements.items():
            a = _quote_anchor(parsed, v["quote"])
            mine[f"elem:{k}"] = (v["value"], [a] if a else [], v["quote"])

    # ---- the measures ---------------------------------------------------
    specs: list[_Spec] = []
    present_rate = {c: sum(1 for e in used if c in e.prof["sections"]) / n for c in CANON_ZH}
    for c, zh in CANON_ZH.items():
        specs.append(_Spec(f"present:{c}", "structure", f"{zh}章节", "", "bool"))
    for c, zh in CANON_ZH.items():
        if present_rate[c] >= 0.5:
            specs.append(_Spec(f"words:{c}", "structure", f"{zh}篇幅占比", "%", "share"))
    for c, zh in CANON_ZH.items():
        if present_rate[c] >= 0.5:
            specs.append(_Spec(f"share:{c}", "distribution", f"{zh}引用占比", "%", "share"))
            if comparable:
                specs.append(_Spec(f"density:{c}", "distribution", f"{zh}每千字引用", "次"))
    specs += [_Spec("sent_ge2", "distribution", "引用两篇及以上的句子占比", "%", "share"),
              _Spec("sent_ge5", "distribution", "引用五篇及以上的句子占比", "%", "share"),
              _Spec("n_refs", "references", "参考文献数量", "条"),
              _Spec("recent_share", "references", "近三年文献占比", "%", "share"),
              _Spec("foreign_share", "references", "外文文献占比", "%", "share"),
              _Spec("ref_age", "references", "文献年龄中位数", "年")]
    specs += [_Spec(f"type:{t}", "references", f"{zh}占比", "%", "share") for t, zh in TYPE_ZH.items()]
    specs += [_Spec(f"func:{f}", "functions", f"{zh}引用占比", "%", "share") for f, zh in FUNC_ZH.items()]
    for k, (label, kind) in ELEMENTS.items():
        specs.append(_Spec(f"elem:{k}", "elements", label, "个" if kind == "number" else "", kind))
    specs += [_Spec("words", "length", "正文字数", "字"),
              _Spec("abstract_chars", "length", "中文摘要字数", "字"),
              _Spec("n_figures", "length", "插图数量", "幅"),
              _Spec("n_tables", "length", "表格数量", "张")]

    metrics: list[VenueMetric] = []
    for sp in specs:
        rows = [(e, ex_vals[e.pdf.doc.id].get(sp.key)) for e in used]
        rows = [(e, v) for e, v in rows if v is not None]
        if not rows:
            continue  # nothing measured on the exemplars (model off)
        vals = [v[0] for _, v in rows if v[0] is not None]
        value, anchors, quote = mine.get(sp.key, (None, [], None))
        m = VenueMetric(key=sp.key, group=sp.group, label=sp.label, unit=sp.unit,  # type: ignore[arg-type]
                        kind=sp.kind, value=value, anchors=anchors, quote=quote,  # type: ignore[arg-type]
                        exemplars=[ExemplarValue(doc_id=e.pdf.doc.id, value=v[0], page=v[1],
                                                 quote=v[2]) for e, v in rows])
        if sp.kind == "bool":
            known = [v for v in vals]
            if len(known) >= 3:
                m.rate = sum(1 for v in known if v) / len(known)
                if value is not None:
                    m.flag = ("below" if not value and m.rate >= 0.75 else
                              "above" if value and m.rate <= 0.25 else "within")
        else:
            m.bench = _q(vals)
            m.flag = _flag(value, m.bench)  # type: ignore[assignment]
        metrics.append(m)

    findings = _findings(metrics, ctx, n, ref_anchor=ra[0] if ra else None)
    infos = [ExemplarInfo(doc_id=e.pdf.doc.id, filename=e.pdf.doc.filename,
                          title=e.pdf.doc.title, year=e.pdf.doc.year,
                          paper_type=paper_type(e.pdf.doc.title),  # type: ignore[arg-type]
                          used=bool(e.prof), similar=e.similar,
                          note=None if e.prof else "没有识别出章节结构或参考文献，未参与统计")
             for e in ctx.exemplars]
    return metrics, findings, infos


# --------------------------------------------------------------- findings


def fmt(v: float | None, unit: str, bare: bool = False) -> str:
    """"51 条" / "44%" / "2.0 年"; ``bare`` drops the unit (range starts)."""
    if v is None:
        return "未知"
    if unit == "%":
        return f"{v:.0%}"
    num = f"{v:.1f}" if unit in {"次", "年"} else f"{v:.0f}"
    return num if bare or not unit else f"{num} {unit}"


def fmt_range(st: Stat, unit: str) -> str:
    return f"{fmt(st.q1, unit, bare=unit != '%')} 至 {fmt(st.q3, unit)}"


# section-level share/density findings already come from the layer;
# only validated research elements raise one
_SKIP_FINDING = re.compile(r"^(share|density|words):|^elem:(?!n_datasets$|has_ablation$)")


def _findings(metrics: list[VenueMetric], ctx: VenueContext, n: int,
              ref_anchor: Anchor | None) -> list[Finding]:
    who = f"《{ctx.venue}》"
    groups: dict[str, list[VenueMetric]] = {}
    for m in metrics:
        if m.flag in {"below", "above"} and not _SKIP_FINDING.match(m.key):
            if m.group == "structure" and m.flag == "above":
                continue  # a section most exemplars lack is not a gap
            groups.setdefault(m.group, []).append(m)
    out: list[Finding] = []
    for g, ms in groups.items():
        bits = []
        for m in ms:
            if m.kind == "bool":
                if g == "structure":
                    bits.append(f"{m.rate:.0%} 的范文有{m.label}，本文没有识别出对应章节")
                elif m.flag == "below":
                    bits.append(f"{m.rate:.0%} 的范文有{m.label}，本文的摘要、章节标题和图表题注中没有发现")
                else:
                    bits.append(f"只有 {m.rate:.0%} 的范文有{m.label}，本文有")
            else:
                side = "低于" if m.flag == "below" else "高于"
                bits.append(f"本文{m.label}为 {fmt(m.value, m.unit)}，{side}范文常见范围 "
                            f"{fmt_range(m.bench, m.unit)}")
        title = (f"缺少{who}范文中常见的章节" if g == "structure" else
                 f"引用多篇文献的句子比例偏离{who}范文的常见范围" if g == "distribution"
                 else f"{GROUP_TITLE[g]}偏离{who}范文的常见范围")
        out.append(Finding(
            id="", layer="distribution", severity="low",
            anchor=ref_anchor if g == "references" else None,
            title=title,
            detail=f"依据：{'；'.join(bits)}。对标 {n} 篇范文。\n"
                   "建议：作为投稿前的参照，由作者判断是否需要调整。",
            refs=[], metrics=[m.key for m in ms],
        ))
    return out


def has_model_reads(ctx: VenueContext | None) -> bool:
    return bool(ctx and any(e.model for e in ctx.used))


__all__ = ["VenueContext", "prepare_venue", "compare", "section_overrides", "fmt",
           "has_model_reads", "CANON_ZH", "GROUP_TITLE"]
