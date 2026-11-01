"""一次性分析：干净稿报警噪音拆解与剔除转换噪声后的估计查准率。

读 reports/<paper>_clean.json（以及注入稿，用来重算查准率），输出：

1. 干净稿报警按 layer × severity、修订按 kind 计数（中英文分开）。
2. 错别字修订逐条归类，识别由 PDF 版面重建 docx 留下的转换痕迹：
   - space    只差空格：PDF 没有空格字符，按字距推断错了（ERNI E、Schoolof）
   - width    全角半角或数字分隔：0．440、88．1、26 260
   - hyphen   连字符：断行连字符丢失或残留（keyvalue、3dSOBS）
   - formula  公式残片：乱码字形（烅、!）、数学符号、两个字母以内的上下标碎片
   - truncate 段首段尾被截断的英文单词（objec、roblems）
   其余记为 other：真错别字或模型误报，没有逐条人工核对。
3. 估计真实查准率：在 evaluate_corpus.py 的单元口径上，把只因转换痕迹错别字
   报警的干净稿单元剔除，其余干净稿报警仍算误报：
       P_est = TP / (TP + 新增误报 + 干净稿既有报警 − 转换噪声单元)
   它比严口径更接近真实值，但仍把原稿本身的真问题（人工核对见 item_bench
   第 7、10 节）计为误报，所以仍是下界。

    python demo/testset/analyze_clean_noise.py            # 读 reports/
    python demo/testset/analyze_clean_noise.py --reports reports_f33
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "backend"))

import evaluate_corpus as ev  # noqa: E402

ZH = ev.PAPERS
EN = ev.PAPERS_EN
MATH = set("∑∏∫_^=<>≤≥±×÷·∂√∞∈∉⊂⊆∀∃→←↔αβγδεθλμσφψωΣΠΔΩ|")
CJK = re.compile(r"[一-鿿]")


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def classify(old: str, new: str, para: str, start: int, end: int, zh: bool) -> str:
    o, n = old or "", new or ""
    if re.sub(r"\s", "", o) == re.sub(r"\s", "", n):
        return "space"
    if re.sub(r"[\s,，]", "", _nfkc(o)) == re.sub(r"[\s,，]", "", _nfkc(n)):
        return "width"
    if (("-" in o) != ("-" in n) or "- " in o) and \
            re.sub(r"[\s\-‐]", "", o).lower() == re.sub(r"[\s\-‐]", "", n).lower():
        return "hyphen"
    if (set(o) | set(n)) & MATH or "!" in o:
        return "formula"
    if any(unicodedata.category(c) == "Co" for c in o):
        return "formula"
    if zh and re.fullmatch(r"[A-Za-z]{1,2}", o.strip()) and re.fullmatch(r"[A-Za-z]{1,2}", n.strip()):
        return "formula"
    if (re.fullmatch(r"[A-Za-z]+", o) and (n.startswith(o) or n.endswith(o))
            and (start == 0 or end >= len(para.rstrip()))):
        return "truncate"
    return "other"


CONVERSION = {"space", "width", "hyphen", "formula", "truncate"}


def raw_breakdown(rep: dict) -> dict:
    sev = Counter((f["layer"], f["severity"]) for f in rep["findings"])
    kinds = Counter(r["kind"] for r in rep["revisions"])
    return {"findings": sev, "revisions": kinds}


def typo_classes(rep: dict, zh: bool) -> list[tuple[dict, str]]:
    paras = {p["id"]: p["text"] for p in rep["paragraphs"]}
    out = []
    for r in rep["revisions"]:
        if r["kind"] != "typo":
            continue
        a = r["anchor"]
        out.append((r, classify(r["old"], r["new"], paras.get(a["paragraph_id"], ""),
                                a["start"], a["end"], zh)))
    return out


def estimated_precision(papers: list[str], reports: Path, zh: bool) -> dict:
    """Recompute evaluate_corpus.score and drop clean-run units whose only
    alarms are typo revisions classified as conversion artifacts."""
    tot = Counter()
    for paper in papers:
        ip, cp = reports / f"{paper}_injected.json", reports / f"{paper}_clean.json"
        if not ip.exists() or not cp.exists():
            continue
        rep_i, rep_c = ev.load(ip), ev.load(cp)
        spec = json.loads((HERE / "injections" / f"{paper}.json").read_text())
        res = ev.score(rep_i, rep_c, spec)
        c = res["counts"]
        for k in ("tp", "fn", "fp_new", "pre_existing", "tn"):
            tot[k] += c[k]
        # map each typo revision of the injected run to its units
        Ui = ev.Units(rep_i)
        paras = {p.id: p.text for p in rep_i.paragraphs}
        unit_typos: dict[tuple, list[str]] = {}
        for v in rep_i.revisions:
            if v.kind != "typo":
                continue
            cls = classify(v.old, v.new, paras.get(v.anchor.paragraph_id, ""),
                           v.anchor.start, v.anchor.end, zh)
            for u in Ui.units_at(v.anchor.paragraph_id, v.anchor.start, v.anchor.end):
                unit_typos.setdefault(u, []).append(cls)
        for item in res["pre_existing_units"]:
            u = tuple(item["unit"])
            al = set(item["alarms"])
            if al == {"revision:typo"}:
                cls = unit_typos.get(u, [])
                tot["pre_typo_only"] += 1
                if cls and all(x in CONVERSION for x in cls):
                    tot["pre_conversion"] += 1
    tp, fp, pre, conv = tot["tp"], tot["fp_new"], tot["pre_existing"], tot["pre_conversion"]
    tot["p_lenient"] = tp / (tp + fp) if tp + fp else 0
    tot["p_strict"] = tp / (tp + fp + pre) if tp + fp + pre else 0
    tot["p_est"] = tp / (tp + fp + pre - conv) if tp + fp + pre - conv else 0
    return dict(tot)


def report(papers: list[str], reports: Path, zh: bool, lines: list[str]) -> dict:
    name = "中文 docx" if zh else "英文 LaTeX"
    fsum, rsum, csum = Counter(), Counter(), Counter()
    samples: dict[str, list[str]] = {}
    for paper in papers:
        p = reports / f"{paper}_clean.json"
        if not p.exists():
            continue
        rep = json.loads(p.read_text("utf-8"))
        b = raw_breakdown(rep)
        fsum.update(b["findings"])
        rsum.update(b["revisions"])
        for r, cls in typo_classes(rep, zh):
            csum[cls] += 1
            samples.setdefault(cls, [])
            if len(samples[cls]) < 6:
                samples[cls].append(f"{r['old']!r}→{r['new']!r}")
    lines.append(f"\n## {name}：干净稿报警（五篇合计）\n")
    lines.append("| 层 | high | medium | low | 合计 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for layer in ("authenticity", "support", "distribution", "norms"):
        h, m, lo = (fsum[(layer, s)] for s in ("high", "medium", "low"))
        lines.append(f"| {layer} | {h} | {m} | {lo} | {h + m + lo} |")
    lines.append("\n| 修订类型 | 条数 |")
    lines.append("| --- | --- |")
    for k, v in rsum.most_common():
        lines.append(f"| {k} | {v} |")
    n_typo = sum(csum.values())
    conv = sum(v for k, v in csum.items() if k in CONVERSION)
    lines.append(f"\n错别字修订 {n_typo} 条，其中疑似转换痕迹 {conv} 条"
                 f"（{conv / n_typo:.1%}）：\n" if n_typo else "\n没有错别字修订。\n")
    if n_typo:
        lines.append("| 类别 | 条数 | 例子 |")
        lines.append("| --- | --- | --- |")
        for k in ("space", "width", "hyphen", "formula", "truncate", "other"):
            if csum[k]:
                lines.append(f"| {k} | {csum[k]} | {'；'.join(samples[k][:4])} |")
    est = estimated_precision(papers, reports, zh)
    if not zh:
        lines.append("\n英文稿件是 arXiv 原始 LaTeX 源码，没有 PDF 转换环节，上表的 space、width 类"
                     "多是标点空格改动，不计为转换噪声，也不做剔除估计。")
        est["p_est"] = est.get("p_strict", 0)
    elif est.get("tp"):
        lines.append(f"\n单元口径（与 evaluate_corpus.py 一致）：TP={est['tp']} 新增误报={est['fp_new']} "
                     f"干净稿既有报警={est['pre_existing']}，其中只因错别字修订报警 "
                     f"{est.get('pre_typo_only', 0)} 个，全部是转换痕迹的 {est.get('pre_conversion', 0)} 个。\n")
        lines.append(f"- 查准率 宽 {est['p_lenient']:.3f}　严 {est['p_strict']:.3f}"
                     f"　**剔除转换噪声后估计 {est['p_est']:.3f}**")
    return {"findings": {f"{a}:{b}": v for (a, b), v in fsum.items()},
            "revisions": dict(rsum), "typo_classes": dict(csum), "precision": est}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", default="reports")
    ap.add_argument("--out", default="results/clean_noise.md")
    args = ap.parse_args()
    reports = HERE / args.reports
    lines = ["# 干净稿报警噪音拆解", "",
             f"由 `analyze_clean_noise.py` 生成，读 `{args.reports}/`。错别字归类规则见脚本文档。"]
    out = {"zh": report(ZH, reports, True, lines), "en": report(EN, reports, False, lines)}
    text = "\n".join(lines) + "\n"
    (HERE / args.out).write_text(text, "utf-8")
    (HERE / args.out).with_suffix(".json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
