"""F24 期刊对标细化的验证：范文章节识别与归类、研究要素、引用功能。

    python demo/testset/venue_bench/eval.py <ref folder> [--model]

The folder is the 《数据分析与知识发现》 exemplar set (38 PDFs). Heading
detection and typing are scored against gold_headings.json, hand-labelled:

- before: the F23 rules (numbered-line regex up to 28 chars, no colon,
  keyword table without 结束语);
- rules: the F24 rules (numbering style, measure words, false-heading
  filter, captions);
- model: rules + the model typing headings the keyword table leaves as
  other (--model, about 0.3 yuan with qwen3.8-flash on 33 papers).

With --model the research elements read from title + abstract + headings
+ captions are also compared with a keyword check over the full text,
and every element's evidence quote is printed for a manual read.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from citecheck.distribution import venue as V  # noqa: E402
from citecheck.library.scan import scan_folder  # noqa: E402
from citecheck.library.text import squash  # noqa: E402
from citecheck.parse.headings import canonical_for  # noqa: E402

HERE = Path(__file__).parent
GOLD = json.loads((HERE / "gold_headings.json").read_text(encoding="utf-8"))["papers"]
_OLD_RE = re.compile(r"^(\d{1,2})\s*([一-鿿A-Za-z][^。；;，,：:]{1,28})$")


def before_headings(pdf) -> list[tuple[str, str]]:
    lines = [ln for ln, _ in V._lines(pdf)]
    ref_at = max((i for i, ln in enumerate(lines) if V._REF_HEAD_RE.match(ln)), default=None)
    if ref_at is None:
        return []
    out, expect = [], 1
    for ln in lines[:ref_at]:
        m = _OLD_RE.match(ln)
        if (m and int(m.group(1)) in (expect, expect + 1) and out or
                m and int(m.group(1)) == 1 and not out) and not re.search(r"\d{3,}", m.group(2)):
            t = m.group(2)
            c = "other" if "结束语" in t else canonical_for(t)
            out.append((t, c))
            expect = int(m.group(1)) + 1
    return out


def score(detected: list[tuple[str, str]], gold: list[list[str]]) -> dict:
    used: set[int] = set()
    right = missed = 0
    for g, ok in gold:
        kg = squash(g)[:6]
        hit = next((i for i, (t, _) in enumerate(detected)
                    if i not in used and (kg in squash(t) or squash(t)[:6] in squash(g))), None)
        if hit is None:
            missed += 1
            continue
        used.add(hit)
        right += detected[hit][1] in ok.split("|")
    return {"gold": len(gold), "right": right, "missed": missed,
            "false": len(detected) - len(used)}


def total(rows: list[dict]) -> dict:
    t = Counter()
    for r in rows:
        t.update(r)
    return dict(t)


_KW = {
    "has_ablation": r"消融",
    "has_case_study": r"案例分析|错误分析|误差分析|个案分析|实例分析|case study|error analysis",
    "has_human_eval": r"人工评估|人工评价|专家评估|专家评价|人工打分|人工评分|human evaluation",
}


async def main(folder: str, use_model: bool) -> None:
    pdfs = {p.doc.filename: p for p in scan_folder(folder)}
    papers = []
    for key, gold in GOLD.items():
        name = next(n for n in pdfs if n.startswith(key))
        papers.append((key, pdfs[name], gold, V.profile_pdf(pdfs[name])))

    res = {"before": [], "rules": [], "model": []}
    overrides: dict[str, str] = {}
    if use_model:
        from citecheck.distribution.venue_model import classify_headings
        overrides = await classify_headings(
            [h["title"] for *_, prof in papers if prof for h in prof["headings"]])
    for key, pdf, gold, prof in papers:
        heads = [(h["title"], h["canonical"]) for h in (prof or {}).get("headings", [])]
        res["before"].append(score(before_headings(pdf), gold))
        res["rules"].append(score(heads, gold))
        if use_model:
            typed = [(t, overrides.get(t, c) if c == "other" else c) for t, c in heads]
            res["model"].append(score(typed, gold))
    lines = ["| 方案 | 金标标题 | 归类正确 | 漏识别 | 误识别 |", "|---|---|---|---|---|"]
    for k, rows in res.items():
        if rows:
            t = total(rows)
            lines.append(f"| {k} | {t['gold']} | {t['right']}（{t['right'] / t['gold']:.0%}） | "
                         f"{t['missed']} | {t['false']} |")
    print("\n".join(lines))

    # captions vs mentions, abstract read
    caps = [p for *_, p in papers if p and p["captions"]]
    print(f"\n题注识别：{len(caps)}/{len(papers)} 篇读到图表题注；"
          f"摘要读出：{sum(1 for *_, p in papers if p and p['abstract'])}/{len(papers)} 篇")

    if not use_model:
        return
    from citecheck.distribution.venue_model import enrich

    reads = await asyncio.gather(*(enrich(p) for *_, p in papers if p))
    agree = Counter()
    known = Counter()
    unknown = Counter()
    funcs = Counter()
    print("\n研究要素证据：")
    for (key, pdf, _g, prof), r in zip([x for x in papers if x[3]], reads):
        body = pdf.body()[0]
        el = r["elements"]
        funcs.update(r["functions"])
        for k, pat in _KW.items():
            v = el[k]["value"]
            if v is None:
                unknown[k] += 1
                continue
            known[k] += 1
            agree[k] += bool(v) == bool(re.search(pat, body, re.I))
        print(f"- {key}: " + "；".join(
            f"{k}={el[k]['value']}" + (f"「{el[k]['quote']}」" if el[k]["quote"] else "")
            for k in el))
    print("\n| 要素 | 有值 | 与全文关键词一致 | 无法判断 |\n|---|---|---|---|")
    for k in _KW:
        print(f"| {k} | {known[k]} | {agree[k]} | {unknown[k]} |")
    n = sum(funcs.values())
    print("\n范文引用功能：" + "，".join(f"{f} {c / n:.0%}" for f, c in funcs.most_common()))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], "--model" in sys.argv))
