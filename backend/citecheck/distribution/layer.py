"""引用分布层：章节引用占比/密度对标、引用堆砌、未标注引用的研究结论、
引用功能分类。

指标口径与 T4a 基准构建一致：章节引用数 = 该节所有标记的 ref_ids 之
和；词数 = 拉丁词元 + CJK 字符；句子引用数 = 一句话内去重后的 ref id
数。论文语言与基准不同（如中文论文对标英文 arXiv 语料）时
comparable_density=False，只比较占比。

Findings（layer=distribution）只在指标落到基准 [q1, q3] 之外时产生，
描述性、severity=low，锚在章节标题段落上；canonical=other 不产生。
"""

from __future__ import annotations

import asyncio
import logging
import re

from pydantic import BaseModel, Field

from ..llm.client import chat_json
from ..parse.parser import ParsedDocument
from ..schema import (
    Anchor,
    Distribution,
    Finding,
    SectionDist,
    SentenceRefs,
    Stat,
)
from ..support.claims import split_sentences
from .bench import load_benchmark

log = logging.getLogger(__name__)

_LATIN = re.compile(r"[A-Za-zÀ-ɏ]+(?:['’-][A-Za-zÀ-ɏ]+)*")
_CJK = re.compile(r"[一-鿿]")

_CANON_ZH = {
    "intro": "引言", "related": "相关工作", "method": "方法",
    "experiment": "实验", "discussion": "讨论", "conclusion": "结论",
    "other": "其他",
}

# 已有研究类提示语：陈述他人研究结论却没有引用时提示
_CUES = [
    "研究表明", "已有研究", "已有工作证明", "大量研究", "有学者指出",
    "previous studies", "previous work", "studies have shown",
    "studies have demonstrated", "it has been shown", "prior work has",
    "is widely reported",
]
_FIRST_PERSON = re.compile(r"\b(?:we|our|us)\b|本文|我们", re.I)

_FUNCS = ["background", "method", "comparison", "result", "critique"]

_FUNC_PROMPT = """\
段落中的 ⟦mN⟧ 是引用标记。判断每个标记在该句中的引用功能，取值仅限：
background（背景）、method（方法）、comparison（对比）、result（结果）、
critique（批评）。以 JSON 输出：
{"items": [{"marker_id": "m0", "function": "background"}]}

段落：
{text}"""


class _FuncItem(BaseModel):
    marker_id: str = ""
    function: str = ""


class _FuncOut(BaseModel):
    items: list[_FuncItem] = Field(default_factory=list)


def count_words(text: str) -> int:
    """Latin word tokens + CJK characters."""
    return len(_LATIN.findall(text)) + len(_CJK.findall(text))


def _paper_lang(parsed: ParsedDocument) -> str:
    text = "\n".join(p.text for p in parsed.paragraphs)
    cjk = len(_CJK.findall(text))
    latin = len(_LATIN.findall(text))
    return "zh" if cjk > latin else "en"


def _flag(value: float, stat: Stat | None) -> str:
    if stat is None:
        return "na"
    if value < stat.q1:
        return "below"
    if value > stat.q3:
        return "above"
    return "within"


def _stat(d: dict | None) -> Stat | None:
    if not d:
        return None
    return Stat(median=d["median"], q1=d["q1"], q3=d["q3"])


async def run_distribution(
    parsed: ParsedDocument,
    *,
    bench_path: str | None = None,
    classify: bool = True,
    route: str = "auto",
) -> tuple[Distribution, list[Finding]]:
    bench = load_benchmark(bench_path)
    bench_sections: dict[str, dict] = bench.get("sections", {})
    bench_lang = bench.get("language", "en")
    para_section = {p.id: p.section_id for p in parsed.paragraphs}
    para_by_id = {p.id: p for p in parsed.paragraphs}
    para_len = {p.id: len(p.text) for p in parsed.paragraphs}
    sec_by_id = {s.id: s for s in parsed.sections}
    markers_by_para: dict[str, list] = {}
    for m in parsed.markers:
        markers_by_para.setdefault(m.paragraph_id, []).append(m)

    comparable = _paper_lang(parsed) == bench_lang
    note = None if comparable else (
        f"论文语言与基准（{bench.get('name', '')}，{bench_lang}）不一致，"
        "引用密度不可比，仅对比占比。")

    # ---- per-section metrics ------------------------------------------
    dist_sections: list[SectionDist] = []
    sec_cites: dict[str, int] = {s.id: 0 for s in parsed.sections}
    sec_words: dict[str, int] = {s.id: 0 for s in parsed.sections}
    for p in parsed.paragraphs:
        sec_words[p.section_id] += count_words(p.text)
    for m in parsed.markers:
        sid = para_section.get(m.paragraph_id)
        if sid:
            sec_cites[sid] += len(m.ref_ids)
    total_cites = sum(sec_cites.values())
    for s in parsed.sections:
        cites = sec_cites[s.id]
        words = sec_words[s.id]
        share = cites / total_cites if total_cites else 0.0
        density = cites * 1000.0 / words if words else 0.0
        bsec = bench_sections.get(s.canonical)
        # only compare canonicals the benchmark actually covers: the
        # section must appear in >=50% of benchmark papers and the IQR
        # must have width > 0 (a degenerate [0,0] range flags everything)
        bshare = _stat((bsec or {}).get("share"))
        bdensity = _stat((bsec or {}).get("density_per_1k_words"))
        if not bsec or bsec.get("present_in", 0) < bench.get("n_papers", 1) / 2:
            bshare = bdensity = None
        if bshare and bshare.q3 - bshare.q1 <= 0:
            bshare = None
        if bdensity and bdensity.q3 - bdensity.q1 <= 0:
            bdensity = None
        dist_sections.append(SectionDist(
            section_id=s.id, canonical=s.canonical, title=s.title,
            words=words, citations=cites, share=share, density=density,
            bench_share=bshare, bench_density=bdensity,
            share_flag=_flag(share, bshare),
            density_flag=_flag(density, bdensity) if comparable else "na",
        ))

    # ---- sentence-level reference counts -------------------------------
    citing_counts: list[int] = []
    stacked: list[tuple[str, int, int, int]] = []  # (para_id, start, end, n)
    for pid, ms in markers_by_para.items():
        text = para_by_id[pid].text
        for sent in split_sentences(text):
            ids: set[str] = set()
            for m in ms:
                if sent.start <= m.start and m.end <= sent.end:
                    ids.update(m.ref_ids)
            if not ids:
                continue
            citing_counts.append(len(ids))
            if len(ids) >= 5:
                stacked.append((pid, sent.start, sent.end, len(ids)))
    n_citing = len(citing_counts)

    def _share(k: int) -> float:
        return sum(1 for c in citing_counts if c >= k) / n_citing if n_citing else 0.0

    bench_sr = bench.get("sentence_refs", {})
    sentence_refs = SentenceRefs(
        share_ge2=_share(2), share_ge3=_share(3), share_ge5=_share(5),
        bench_ge2=_stat(bench_sr.get("share_ge2")),
        bench_ge3=_stat(bench_sr.get("share_ge3")),
        bench_ge5=_stat(bench_sr.get("share_ge5")),
    )

    # ---- citation function classification -------------------------------
    functions: dict[str, int] | None = None
    marker_functions: dict[str, str] = {}
    if classify:
        functions = {f: 0 for f in _FUNCS}

        def _tagged(text: str, ms) -> str:
            out = []
            cur = 0
            for m in sorted(ms, key=lambda x: x.start):
                out.append(text[cur:m.start])
                out.append(f"⟦{m.id}⟧")
                cur = m.end
            out.append(text[cur:])
            return "".join(out)

        async def _classify_para(pid, ms):
            text = para_by_id[pid].text
            res = await chat_json(
                "function",
                [{"role": "user",
                  "content": _FUNC_PROMPT.replace("{text}", _tagged(text, ms))}],
                _FuncOut, route=route,
            )
            if res.value is None:
                return
            valid = {m.id for m in ms}
            for it in res.value.items:
                if it.marker_id in valid and it.function in _FUNCS:
                    marker_functions[it.marker_id] = it.function
                    functions[it.function] += 1

        await asyncio.gather(
            *[_classify_para(pid, ms) for pid, ms in markers_by_para.items()]
        )

    dist = Distribution(
        benchmark_id=bench.get("id", ""), benchmark_name=bench.get("name", ""),
        n_papers=bench.get("n_papers", 0), comparable_density=comparable,
        note=note, sections=dist_sections, sentence_refs=sentence_refs,
        functions=functions, marker_functions=marker_functions,
    )

    # ---- findings --------------------------------------------------------
    findings: list[Finding] = []
    for sd in dist_sections:
        if sd.canonical == "other":
            continue
        sec = sec_by_id[sd.section_id]
        hp = sec.heading_paragraph_id
        anchor = (
            Anchor(paragraph_id=hp, start=0, end=para_len.get(hp, len(sec.title)))
            if hp else None
        )
        name = _CANON_ZH.get(sd.canonical, sd.title or sd.canonical)
        n_papers = bench.get("n_papers", 0)
        bname = bench.get("name", "基准")
        # at most one finding per section; share and density merge
        bits: list[str] = []
        share_out = sd.share_flag in {"below", "above"} and sd.bench_share
        dens_out = (
            comparable and sd.density_flag in {"below", "above"}
            and sd.bench_density and sd.words > 0
        )
        if share_out:
            side = "低于" if sd.share_flag == "below" else "高于"
            bits.append(f"引用占比 {sd.share * 100:.1f}%{side}常见范围 "
                        f"{sd.bench_share.q1 * 100:.1f}% 至 "
                        f"{sd.bench_share.q3 * 100:.1f}%")
        if dens_out:
            side = "低于" if sd.density_flag == "below" else "高于"
            bits.append(f"每千词引用 {sd.density:.1f} 次{side}常见范围 "
                        f"{sd.bench_density.q1:.1f} 至 "
                        f"{sd.bench_density.q3:.1f} 次")
        if bits:
            findings.append(Finding(
                id="", layer="distribution", severity="low", anchor=anchor,
                title=f"{name}部分的引用分布偏离该领域常见范围",
                detail=f"依据：本文{name}部分{'，'.join(bits)}，对标的 "
                       f"{n_papers} 篇{bname}论文。\n"
                       f"建议：确认{name}部分对已有方法、数据集和工具"
                       "的引用是否恰当。",
                refs=[],
            ))

    for pid, s, e, n in stacked:
        findings.append(Finding(
            id="", layer="distribution", severity="medium",
            anchor=Anchor(paragraph_id=pid, start=s, end=e),
            title=f"这句话同时引用了 {n} 篇文献",
            detail="依据：一句话内集中引用了多篇文献。\n"
                   "建议：确认每篇文献与这句话的具体关系，"
                   "必要时拆分或给出各自的对应点。",
            refs=[],
        ))

    # 未标注引用的"已有研究"式结论（只在 intro/related/discussion）
    cue_secs = {
        s.id for s in parsed.sections
        if s.canonical in {"intro", "related", "discussion"}
    }
    for p in parsed.paragraphs:
        if p.section_id not in cue_secs:
            continue
        ms = markers_by_para.get(p.id, [])
        for sent in split_sentences(p.text):
            if any(sent.start <= m.start and m.end <= sent.end for m in ms):
                continue
            low = sent.text.lower()
            if _FIRST_PERSON.search(sent.text):
                continue
            if not any(c in sent.text or c in low for c in _CUES):
                continue
            findings.append(Finding(
                id="", layer="distribution", severity="medium",
                anchor=Anchor(paragraph_id=p.id, start=sent.start,
                              end=sent.end),
                title="这句话陈述了已有研究结论，但没有标注引用",
                detail="依据：句子使用了“已有研究”类表述，未给出引用。\n"
                       "建议：若结论出自他人工作，请标注对应文献。",
                refs=[],
            ))

    for i, f in enumerate(findings):
        f.id = f"dist-{i}"
    return dist, findings
