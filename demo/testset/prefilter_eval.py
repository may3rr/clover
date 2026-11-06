"""BM25 预选对向量计算量和体检结果的影响（离线对照）。

用一次冷启动留下的缓存库（向量、检索、抽取都已缓存）按不同的
[llm.embedding] prefilter_k 各重跑一次。每次先复制一份缓存库，所以各组
互不影响；预选后的向量全部命中缓存，只有候选集变化后的重排与判断会真正
调用云端。

统计：
  embedded   需要算向量的不同片段数（本机向量时就是 NPU 的工作量）
  changed    与 k=0 相比判断结论不同的（论断，文献）对
  findings   发现条数，注入检出由 demo/final/check_final.py 给出

    python demo/testset/prefilter_eval.py --tag zh --cache /tmp/prof_zh_1106.sqlite \\
        --input "demo/final/演示稿/基于深度学习的目标检测研究综述.docx" \\
        --library "demo/final/演示稿/ref" --k 0 64 128 256
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "results" / "prefilter"


def run_one(args) -> None:
    """Child process: one pipeline run with a given prefilter_k."""
    os.environ["CITECHECK_CACHE"] = args.db
    sys.path.insert(0, str(ROOT / "backend"))
    from citecheck.config import get_settings
    from citecheck.llm import embed as E
    from citecheck.pipeline import run_pipeline

    cfg = get_settings().llm.embedding
    cfg.prefilter_k = args.one
    cfg.prefilter_neighbors = args.radius
    seen: set[str] = set()
    calls = {"windows": 0}
    orig = E.embed

    def counting(texts, query=False):
        if not query:
            calls["windows"] += len(texts)
            seen.update(texts)
        return orig(texts, query=query)

    E.embed = counting
    t0 = time.monotonic()
    report = asyncio.run(run_pipeline(Path(args.input), library_dir=args.library))
    wall = round(time.monotonic() - t0, 1)
    Path(args.save).write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False),
                               "utf-8")
    print(json.dumps({"k": args.one, "embedded": len(seen), "embed_inputs": calls["windows"],
                      "wall_s": wall}))


def labels(path: Path) -> dict[tuple[str, str], str]:
    r = json.loads(path.read_text("utf-8"))
    claims = {c["id"]: c["text"] for c in r["claims"]}
    return {(claims.get(s["claim_id"], s["claim_id"]), s["ref_id"]): s["label"]
            for s in r["support_checks"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--cache", required=True, help="冷启动留下的缓存库，只读")
    ap.add_argument("--input", required=True)
    ap.add_argument("--library", default=None)
    ap.add_argument("--injections", default=None, help="英文演示稿的注入清单")
    ap.add_argument("--k", type=int, nargs="+", default=[0, 64, 128, 256])
    ap.add_argument("--radius", type=int, default=1)
    ap.add_argument("--one", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--db", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--save", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.one is not None:
        run_one(args)
        return

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    base: dict | None = None
    for k in args.k:
        db = Path(f"/tmp/prefilter_{args.tag}_{k}.sqlite")
        for suffix in ("", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        shutil.copy(args.cache, db)
        report = OUT / f"{args.tag}_k{k}.json"
        cmd = [sys.executable, __file__, "--tag", args.tag, "--cache", args.cache,
               "--input", args.input, "--one", str(k), "--radius", str(args.radius),
               "--db", str(db), "--save", str(report)]
        if args.library:
            cmd += ["--library", args.library]
        out = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        stat = json.loads(out.stdout.strip().splitlines()[-1])
        lab = labels(report)
        r = json.loads(report.read_text("utf-8"))
        check = [sys.executable, str(ROOT / "demo/final/check_final.py"), str(report)]
        if args.injections:
            check.append(args.injections)
        score = subprocess.run(check, capture_output=True, text=True, cwd=ROOT).stdout
        hit = next((ln for ln in score.splitlines() if "/" in ln and ("检出" in ln or "caught" in ln.lower())), score.strip().splitlines()[-1] if score.strip() else "")
        row = {**stat, "pairs": len(lab), "findings": len(r["findings"]), "score": hit.strip()}
        if base is None:
            base = {"labels": lab, "embedded": stat["embedded"]}
        else:
            common = set(lab) & set(base["labels"])
            row["changed"] = sum(lab[p] != base["labels"][p] for p in common)
            row["share"] = round(stat["embedded"] / max(1, base["embedded"]), 3)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (OUT / f"{args.tag}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()
