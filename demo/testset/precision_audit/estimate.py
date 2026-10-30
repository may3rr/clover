"""Precision audit, step 2: estimate the true precision from hand labels.

Reads sample.json (written by build_pool.py) and labels.csv (exported from
annotate.html). Per stratum h with N_h pooled alarms and n_h labelled ones,
the share of real problems p_h is scaled up to the stratum, giving the
estimated number of real problems among the clean-run alarms
R = sum_h N_h * p_h, and

    precision = (TP + R) / (TP + FP_new + N_pre)

with TP / FP_new / N_pre from the same evaluate_corpus run. "转换痕迹" and
"无法判断" are reported two ways: counted as false positives (as above), or
left out of the denominator (N_pre minus their estimated count E).

95% intervals come from a stratified bootstrap: labels are resampled with
replacement within each stratum; strata labelled in full (n_h = N_h) are
fixed, since they carry no sampling error.

Usage:
    python demo/testset/precision_audit/estimate.py
    python demo/testset/precision_audit/estimate.py --audit DIR --labels FILE --out FILE
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TESTSET = HERE.parent

REAL, FP, CONV, UNK = "真问题", "误报", "转换痕迹", "无法判断"
LABELS = [REAL, FP, CONV, UNK]
LANG_NAME = {"zh": "中文", "en": "英文"}


def load_labels(path: Path, sample: dict) -> dict[str, str]:
    known = {i for d in sample["langs"].values() for s in d["strata"].values() for i in s["ids"]}
    out, unknown = {}, 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            iid, lab = row.get("id", "").strip(), row.get("label", "").strip()
            if iid not in known:
                unknown += 1
                continue
            if lab and lab not in LABELS:
                raise SystemExit(f"{path}: unknown label {lab!r} for {iid}")
            if lab:
                out[iid] = lab
    if unknown:
        print(f"warning: {unknown} rows in {path.name} are not in this sample, ignored",
              file=sys.stderr)
    return out


def estimate_lang(d: dict, labels: dict[str, str], boot: int, rng) -> dict:
    tp, fp, n_pre = d["tp"], d["fp_new"], d["pre_existing"]
    strata, missing = [], []
    for h, s in d["strata"].items():
        labs = [labels[i] for i in s["ids"] if i in labels]
        if not labs:
            missing.append(h)
        strata.append({"name": h, "N": s["N"], "n": s["n"], "labs": labs,
                       "counts": {k: labs.count(k) for k in LABELS}})
    if missing:
        raise SystemExit("no labels yet for stratum: " + "; ".join(missing))

    R = E = 0.0
    R_b = np.zeros(boot)
    E_b = np.zeros(boot)
    for s in strata:
        real = np.array([x == REAL for x in s["labs"]], dtype=float)
        excl = np.array([x in (CONV, UNK) for x in s["labs"]], dtype=float)
        R += s["N"] * real.mean()
        E += s["N"] * excl.mean()
        if len(real) >= s["N"]:  # census: no sampling error
            R_b += s["N"] * real.mean()
            E_b += s["N"] * excl.mean()
            continue
        idx = rng.integers(0, len(real), size=(boot, len(real)))
        R_b += s["N"] * real[idx].mean(axis=1)
        E_b += s["N"] * excl[idx].mean(axis=1)

    def ci(x):
        return tuple(float(v) for v in np.percentile(x, [2.5, 97.5]))

    prec_fp = (tp + R) / (tp + fp + n_pre)
    prec_fp_b = (tp + R_b) / (tp + fp + n_pre)
    prec_ex = (tp + R) / (tp + fp + n_pre - E)
    prec_ex_b = (tp + R_b) / (tp + fp + n_pre - E_b)
    return {
        "tp": tp, "fp": fp, "n_pre": n_pre, "strata": strata,
        "labelled": sum(len(s["labs"]) for s in strata),
        "sampled": sum(s["n"] for s in strata),
        "R": (R, ci(R_b)), "E": (E, ci(E_b)),
        "share": (R / n_pre, ci(R_b / n_pre)),
        "as_fp": (prec_fp, ci(prec_fp_b)),
        "excluded": (prec_ex, ci(prec_ex_b)),
        "lenient": tp / (tp + fp) if tp + fp else None,
        "strict": tp / (tp + fp + n_pre) if tp + fp + n_pre else None,
    }


def f3(x):
    return "-" if x is None else f"{x:.3f}"


def iv(v):
    return f"{v[1][0]:.3f} 至 {v[1][1]:.3f}"


def report(sample: dict, res: dict, labels_path: Path, boot: int, seed: int) -> str:
    out = ["# 干净稿既有报警人工核对与查准率估计\n",
           f"报告目录 `{sample.get('reports', '')}`，标注文件 `{labels_path.name}`，"
           f"生成于 {date.today().isoformat()}。\n",
           "## 抽样设计\n",
           "抽样单元与 `evaluate_corpus.py` 的评测单元一致：一条引用句、一条参考文献或一个无引用的句子。"
           "报警池即该脚本判为干净稿既有报警的全部单元。一个单元可能挂多条报警，按真实性、支持度、"
           "分布、规范、错别字修订的先后取第一条报警的类别作为它的层，各层合计等于报警池总数。"
           f"按各层占比分配名额，每层至少 {sample['floor']} 条，不足 {sample['floor']} 条的层全部纳入，"
           f"随机种子 {sample['seed']}。标注时只要单元上有一条报警成立即记为真问题。\n"]
    for lang, r in res.items():
        out += [f"### {LANG_NAME[lang]}\n",
                f"报警池 {r['n_pre']} 条，抽样 {r['sampled']} 条，已标注 {r['labelled']} 条。\n",
                "| 层 | 总数 | 抽样数 | 已标注 | 权重 |", "| --- | --- | --- | --- | --- |"]
        for s in r["strata"]:
            out.append(f"| {s['name']} | {s['N']} | {s['n']} | {len(s['labs'])} | "
                       f"{s['N'] / r['n_pre']:.3f} |")
        out.append("")

    out.append("## 各层标注结果\n")
    for lang, r in res.items():
        out += [f"### {LANG_NAME[lang]}\n",
                "| 层 | 已标注 | 真问题 | 误报 | 转换痕迹 | 无法判断 | 真问题比例 |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        tot = {k: 0 for k in LABELS}
        for s in r["strata"]:
            c = s["counts"]
            for k in LABELS:
                tot[k] += c[k]
            out.append(f"| {s['name']} | {len(s['labs'])} | {c[REAL]} | {c[FP]} | {c[CONV]} | "
                       f"{c[UNK]} | {c[REAL] / len(s['labs']):.3f} |")
        n = sum(tot.values())
        out += [f"| 未加权合计 | {n} | {tot[REAL]} | {tot[FP]} | {tot[CONV]} | {tot[UNK]} | "
                f"{tot[REAL] / n:.3f} |", ""]

    out += ["## 查准率估计\n",
            "估计查准率 = (TP + 估计真问题数) ÷ (TP + 新增误报 + 既有报警总数)。"
            "转换痕迹和无法判断分两种口径：计为误报，或从分母剔除，即分母减去其估计条数。"
            f"区间为分层自助法 {boot} 次重抽样的 2.5 与 97.5 百分位，随机种子 {seed}；"
            "整层纳入的层不参与重抽样。\n",
            "| 语言 | TP | 新增误报 | 既有报警 | 估计真问题数 | 真问题占既有报警 | 估计剔除数 | "
            "查准率 计为误报 | 95% 区间 | 查准率 剔除 | 95% 区间 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for lang, r in res.items():
        out.append(f"| {LANG_NAME[lang]} | {r['tp']} | {r['fp']} | {r['n_pre']} | "
                   f"{r['R'][0]:.1f}，区间 {r['R'][1][0]:.1f} 至 {r['R'][1][1]:.1f} | "
                   f"{r['share'][0]:.3f} | {r['E'][0]:.1f} | "
                   f"**{r['as_fp'][0]:.3f}** | {iv(r['as_fp'])} | "
                   f"**{r['excluded'][0]:.3f}** | {iv(r['excluded'])} |")
    out += ["", "对照：`results/summary.md` 与 `summary_en.md` 的两个边界口径。\n",
            "| 语言 | 宽口径 | 严口径 |", "| --- | --- | --- |"]
    for lang, r in res.items():
        out.append(f"| {LANG_NAME[lang]} | {f3(r['lenient'])} | {f3(r['strict'])} |")
    out += ["", "## 说明\n",
            "- TP、新增误报与既有报警总数取自同一批报告的 `evaluate_corpus.py` 结果，视为固定值，"
            "区间只反映抽样误差，不包含标注者判断的不确定性。",
            "- 某层标注结果全部相同时，自助法在该层没有波动，小层的区间会偏窄。",
            "- 自助法未做有限总体校正，抽样比例较高的层区间偏宽。", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--audit", type=Path, default=HERE, help="folder with sample.json")
    ap.add_argument("--labels", type=Path, help="default: <audit>/labels.csv")
    ap.add_argument("--out", type=Path, default=TESTSET / "results" / "precision_audit.md")
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    sample = json.loads((args.audit / "sample.json").read_text(encoding="utf-8"))
    labels_path = args.labels or args.audit / "labels.csv"
    if not labels_path.exists():
        raise SystemExit(f"{labels_path} not found: export it from annotate.html first")
    labels = load_labels(labels_path, sample)
    rng = np.random.default_rng(args.seed)
    res = {lang: estimate_lang(d, labels, args.boot, rng) for lang, d in sample["langs"].items()}

    md = report(sample, res, labels_path, args.boot, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    for lang, r in res.items():
        print(f"{lang}: labelled {r['labelled']}/{r['sampled']}  "
              f"as_fp {r['as_fp'][0]:.3f} [{iv(r['as_fp'])}]  "
              f"excluded {r['excluded'][0]:.3f} [{iv(r['excluded'])}]")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
