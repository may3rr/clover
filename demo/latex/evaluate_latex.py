"""在 LaTeX 样例集上跑真实管线并按注入清单打分。

    python demo/latex/evaluate_latex.py              # 全部样例，真实调用
    python demo/latex/evaluate_latex.py bert         # 指定样例
    python demo/latex/evaluate_latex.py --reuse      # 复用 reports/ 里的报告

每篇的报告存 reports/<name>.json，批注版导出存 export/<name>（Clover）.zip，
汇总写 eval_result.json。

检出规则（与 demo/evaluate.py 的 docx 版一致，不放宽）：
  fake_ref       该条目 RefCheck=not_found，且有一条挂在它上面的高严重度真实性问题
  wrong_year     该条目 RefCheck=mismatch，issues 里有「年份」
  wrong_author   该条目 RefCheck=mismatch，issues 里有「作者」
  misattribution 含注入句的论断对该条目判为 unsupported，且有一条挂在该句上的
                 高严重度支持度问题；只给出「可能引错了文献」（off_topic，中）
                 不算检出，单独列为提示
  typo           有一条修订 old 含错词、new 含正确词
  undefined_key  规范层「正文引用找不到对应的参考文献条目」问题提到该键
另外报告：原文自带的错别字（natural_typos）是否检出；没有对应注入的高严重度
问题逐条列出（原论文本身也可能有真实问题，不计入检出率，由人工判断）。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from citecheck.export.latex import PATCH_NAME, export_latex  # noqa: E402
from citecheck.pipeline import run_pipeline  # noqa: E402
from citecheck.schema import Report  # noqa: E402

SPEC = HERE / "injections.json"
SAMPLES = HERE / "samples"
REPORTS = HERE / "reports"
EXPORTS = HERE / "export"
RESULT = HERE / "eval_result.json"


async def _run(name: str) -> Report:
    report = await run_pipeline(SAMPLES / f"{name}.zip")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{name}.json").write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False,
                   indent=1) + "\n", encoding="utf-8")
    return report


def _score(paper: dict, rep: Report) -> dict:
    ref_by_key = {r.key: r for r in rep.references if r.key}
    rc_by_id = {c.ref_id: c for c in rep.ref_checks}
    para = {p.id: p for p in rep.paragraphs}
    claims = {c.id: c for c in rep.claims}
    explained: set[str] = set()
    rows = []

    def ref_findings(rid: str, layer: str):
        return [f for f in rep.findings if f.layer == layer and rid in f.refs]

    for inj in paper["injections"]:
        kind, ok, why = inj["kind"], False, ""
        ref = ref_by_key.get(inj.get("key"))
        rc = rc_by_id.get(ref.id) if ref else None
        if kind == "fake_ref":
            hits = [f for f in ref_findings(ref.id, "authenticity")
                    if f.severity == "high"] if ref else []
            ok = bool(rc and rc.status == "not_found" and hits)
            why = rc.status if rc else "无核验结果"
            explained |= {f.id for f in hits}
        elif kind in {"wrong_year", "wrong_author"}:
            word = "年份" if kind == "wrong_year" else "作者"
            ok = bool(rc and rc.status == "mismatch"
                      and any(word in i for i in rc.issues))
            why = f"{rc.status}: {'；'.join(rc.issues)}" if rc else "无核验结果"
            if ok and ref:
                explained |= {f.id for f in ref_findings(ref.id, "authenticity")}
        elif kind == "misattribution":
            snippet = inj["snippet"]
            pairs = [s for s in rep.support_checks
                     if ref and s.ref_id == ref.id
                     and s.claim_id in claims
                     and snippet in para[claims[s.claim_id].paragraph_id].text]
            labels = [(s.label, s.off_topic) for s in pairs]
            fs = [f for f in ref_findings(ref.id, "support")
                  if f.anchor and snippet in para[f.anchor.paragraph_id].text
                  ] if ref else []
            ok = any(lb == "unsupported" for lb, _ in labels) and any(
                f.severity == "high" for f in fs)
            hint = not ok and any(off for _, off in labels)
            why = (str(labels) or "没有对应的论断") + (
                "（只提示了可能引错文献，不计入检出）" if hint else "")
            explained |= {f.id for f in fs}
        elif kind == "typo":
            revs = [r for r in rep.revisions
                    if inj["wrong"] in r.old and inj["right"] in r.new]
            ok = bool(revs)
            why = f"{revs[0].old} → {revs[0].new}" if revs else "没有对应修订"
        elif kind == "undefined_key":
            fs = [f for f in rep.findings
                  if f.title == "正文引用找不到对应的参考文献条目"
                  and inj["key"] in f.detail]
            ok = bool(fs)
            why = "已报告" if ok else "未报告"
            explained |= {f.id for f in fs}
        rows.append({"id": inj["id"], "kind": kind, "detected": ok,
                     "evidence": why})

    natural = []
    for t in paper.get("natural_typos", []):
        natural.append({"wrong": t["wrong"], "detected": any(
            t["wrong"] in r.old and t["right"] in r.new for r in rep.revisions)})
    unexplained = [
        {"id": f.id, "layer": f.layer, "title": f.title,
         "loc": f.anchor.loc if f.anchor else None}
        for f in rep.findings if f.severity == "high" and f.id not in explained]
    return {"rows": rows, "natural_typos": natural,
            "unexplained_high": unexplained,
            "duration_s": rep.meta.duration_s if rep.meta else None}


def _check_export(name: str, rep: Report) -> dict:
    EXPORTS.mkdir(exist_ok=True)
    out = export_latex(SAMPLES / f"{name}.zip", rep,
                       EXPORTS / f"{name}（Clover）.zip")
    info = {"path": str(out.relative_to(HERE)), "patch_applies": None}
    with zipfile.ZipFile(out) as zf:
        if PATCH_NAME not in zf.namelist():
            return info
        tmp = EXPORTS / f".{name}-check"
        shutil.rmtree(tmp, ignore_errors=True)
        zf.extractall(tmp)
    if shutil.which("git"):
        # patch paths are relative to the exported project root
        r = subprocess.run(["git", "apply", "--check", PATCH_NAME],
                           cwd=tmp, capture_output=True, text=True)
        info["patch_applies"] = r.returncode == 0
    shutil.rmtree(tmp, ignore_errors=True)
    return info


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    reuse = "--reuse" in sys.argv
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    papers = [p for p in spec["papers"] if not args or p["name"] in args]
    results = {}
    for paper in papers:
        name = paper["name"]
        cached = REPORTS / f"{name}.json"
        if reuse and cached.is_file():
            rep = Report.model_validate(json.loads(cached.read_text("utf-8")))
        else:
            print(f"running {name} …", flush=True)
            rep = asyncio.run(_run(name))
        res = _score(paper, rep)
        res["export"] = _check_export(name, rep)
        results[name] = res
        got = sum(r["detected"] for r in res["rows"])
        print(f"\n== {name}  {got}/{len(res['rows'])}  "
              f"用时 {res['duration_s']}s  导出补丁可用={res['export']['patch_applies']}")
        for r in res["rows"]:
            print(f"  {'✓' if r['detected'] else '✗'} {r['id']:14} {r['evidence'][:110]}")
        for t in res["natural_typos"]:
            print(f"  {'✓' if t['detected'] else '✗'} 原文错别字 {t['wrong']}")
        for f in res["unexplained_high"]:
            print(f"  ? 未对应注入的高严重度问题 [{f['layer']}] {f['title']} @ {f['loc']}")
    total = sum(len(r["rows"]) for r in results.values())
    got = sum(sum(x["detected"] for x in r["rows"]) for r in results.values())
    by_kind: dict[str, list[int]] = {}
    for r in results.values():
        for x in r["rows"]:
            by_kind.setdefault(x["kind"], [0, 0])
            by_kind[x["kind"]][0] += x["detected"]
            by_kind[x["kind"]][1] += 1
    summary = {"detected": got, "total": total,
               "by_kind": {k: f"{a}/{b}" for k, (a, b) in by_kind.items()}}
    print(f"\n总计 {got}/{total}  " + "  ".join(
        f"{k} {v}" for k, v in summary["by_kind"].items()))
    if not args:
        RESULT.write_text(json.dumps({"summary": summary, "papers": results},
                                     ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
