"""速度与云端成本基线剖析（PRE_HACKATHON_BASELINE.md 第 3 节的数据来源）。

两个子命令：

  run     用一个独立的缓存库跑一次完整体检，记下墙钟时间、各层耗时、外部检索
          耗时，以及本次运行写进该缓存库 llm_usage 表的逐任务调用数与 token。
          同一个 --cache 第一次是冷启动（所有模型、向量、重排、检索都是真实请求），
          第二次是热缓存（全部命中）。

  report  汇总 profile_runs/*.json 与主缓存库 llm_usage 的逐任务平均 token，
          按两种配置折算一篇标准论文的冷启动云端成本，写 results/cost_speed.md。

    python demo/testset/profile_cost_speed.py run --tag zh_demo --cache /tmp/prof_zh.sqlite \\
        demo/final/演示稿/基于深度学习的目标检测研究综述.docx demo/final/演示稿/ref
    python demo/testset/profile_cost_speed.py run --tag zh_demo --cache /tmp/prof_zh.sqlite ...   # 再跑一次 = 热缓存
    python demo/testset/profile_cost_speed.py report

价格（元 / 百万 token）取 backend/citecheck/config.py 的 _DEFAULT_PRICES（百炼北京地域原价，
2026-10），向量与重排按百炼 text-embedding-v4、qwen3-rerank 原价 0.5，只计输入。实际扣费以
控制台账单为准。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RUNS = HERE / "profile_runs"
MAIN_CACHE = Path("~/Library/Application Support/citecheck/cache.sqlite").expanduser()

# 元 / 百万 token（输入, 输出）
PRICE = {
    "qwen3.8-flash": (0.8, 2.7),
    "qwen3.8-max": (12.0, 36.0),
    "embed": (0.5, 0.0),     # 百炼 text-embedding-v4
    "rerank": (0.5, 0.0),    # 百炼 qwen3-rerank
}
CHAT_TASKS = ["structure", "extract", "judge", "review", "typo", "function",
              "profile", "overview"]


# ------------------------------------------------------------------ run

def _usage_since(db: Path, last_id: int) -> list[dict]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM llm_usage WHERE id > ?", (last_id,))]
    con.close()
    return rows


def _max_id(db: Path) -> int:
    if not db.exists():
        return 0
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COALESCE(MAX(id), 0) FROM llm_usage").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        con.close()


def cmd_run(args) -> int:
    db = Path(args.cache).expanduser().resolve()
    os.environ["CITECHECK_CACHE"] = str(db)
    sys.path.insert(0, str(ROOT / "backend"))
    from citecheck.pipeline import run_pipeline  # noqa: E402

    phase = "warm" if db.exists() and _max_id(db) > 0 else "cold"
    before = _max_id(db)
    t0 = time.monotonic()
    report = asyncio.run(run_pipeline(Path(args.input), library_dir=args.library))
    wall = round(time.monotonic() - t0, 1)
    if args.save:
        Path(args.save).write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False),
                                   "utf-8")
    rows = _usage_since(db, before)

    by_task: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cached": 0,
                                                    "prompt": 0, "completion": 0,
                                                    "models": set()})
    for r in rows:
        t = by_task[r["task"]]
        t["calls"] += 1
        t["cached"] += r["cached"]
        t["prompt"] += r["prompt_tokens"]
        t["completion"] += r["completion_tokens"]
        t["models"].add(r["model"])
    tasks = {k: {**v, "models": sorted(v["models"])} for k, v in by_task.items()}

    m = report.meta
    out = {
        "tag": args.tag, "phase": phase, "input": args.input, "library": args.library,
        "wall_s": wall, "duration_s": m.duration_s,
        "timings": m.timings,
        "size": {"paragraphs": len(report.paragraphs), "references": len(report.references),
                 "markers": len(report.markers), "claims": len(report.claims),
                 "support_checks": len(report.support_checks),
                 "linked_pdfs": len(report.library.links) if report.library else 0},
        "tasks": tasks,
        "findings": len(report.findings), "revisions": len(report.revisions),
    }
    RUNS.mkdir(exist_ok=True)
    dst = RUNS / f"{args.tag}_{phase}.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps({k: out[k] for k in ("tag", "phase", "wall_s", "timings", "size")},
                     ensure_ascii=False, indent=1))
    print("tasks:", {k: (v["calls"], v["cached"]) for k, v in tasks.items()})
    print("->", dst)
    return 0


# --------------------------------------------------------------- report

def task_averages(db: Path) -> dict[str, dict]:
    """Average tokens per real (uncached) Qwen call, per task, over the whole
    usage log. DeepSeek rows (an earlier English run) are left out."""
    con = sqlite3.connect(db)
    out = {}
    for task, model, n, p, c, pm in con.execute(
            "SELECT task, model, COUNT(*), AVG(prompt_tokens), AVG(completion_tokens), "
            "MAX(prompt_tokens) FROM llm_usage WHERE cached = 0 AND model LIKE 'qwen3.8-%' "
            "GROUP BY task, model"):
        out.setdefault(task, {})[model] = {"n": n, "prompt": p, "completion": c, "pmax": pm}
    for task in ("embed", "rerank"):
        row = con.execute(
            "SELECT COUNT(*), AVG(prompt_tokens) FROM llm_usage WHERE cached = 0 AND task = ? "
            "AND model NOT LIKE 'deepseek%'", (task,)).fetchone()
        out[task] = {"*": {"n": row[0], "prompt": row[1] or 0, "completion": 0, "pmax": None}}
    con.close()
    return out


def _cost(model_key: str, p: float, c: float) -> float:
    i, o = PRICE[model_key]
    return p / 1e6 * i + c / 1e6 * o


def cmd_report(args) -> int:
    runs = [json.loads(p.read_text("utf-8")) for p in sorted(RUNS.glob("*.json"))]
    avg = task_averages(MAIN_CACHE)
    L = ["# 速度与云端成本基线", "",
         "由 `profile_cost_speed.py report` 生成。价格为百炼北京地域原价（元/百万 token），"
         "qwen3.8-flash 输入 0.8 输出 2.7，qwen3.8-max 输入 12 输出 36，向量 text-embedding-v4 "
         "与重排 qwen3-rerank 各 0.5（只计输入）。", ""]

    # ---- per-task averages over the whole usage log
    L += ["## 1. 逐任务平均 token（主缓存库全部真实调用）", "",
          "| 任务 | 模型 | 真实调用次数 | 平均输入 | 平均输出 |", "| --- | --- | --- | --- | --- |"]
    for task in CHAT_TASKS + ["embed", "rerank"]:
        for model, a in sorted((avg.get(task) or {}).items()):
            L.append(f"| {task} | {model} | {a['n']} | {a['prompt']:.0f} | {a['completion']:.0f} |")
    L.append("")

    # ---- measured runs
    L += ["## 2. 实测运行", "",
          "| 运行 | 阶段 | 墙钟 s | 解析 s | 真实性 s | 支持度 s | 分布 s | 规范 s | 段落 | 条目 | 引用标记 | 论断 | 模型调用 | 其中缓存命中 |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in runs:
        lt = r["timings"].get("layers", {})
        calls = sum(v["calls"] for k, v in r["tasks"].items() if k in CHAT_TASKS)
        hit = sum(v["cached"] for k, v in r["tasks"].items() if k in CHAT_TASKS)
        s = r["size"]
        L.append(f"| {r['tag']} | {r['phase']} | {r['wall_s']} | {r['timings'].get('parse')} | "
                 f"{lt.get('authenticity')} | {lt.get('support')} | {lt.get('distribution')} | "
                 f"{lt.get('norms')} | {s['paragraphs']} | {s['references']} | {s['markers']} | "
                 f"{s['claims']} | {calls} | {hit} |")
    L.append("")
    L.append("四层并发运行，各层耗时从开始到该层结束计，墙钟约等于最慢的一层（通常是支持度）。")
    L.append("")
    for r in runs:
        if r["phase"] != "cold":
            continue
        src = r["timings"].get("sources", {})
        if src:
            L.append(f"- {r['tag']} 冷启动外部检索：" + "；".join(
                f"{k} {v['calls']} 次（缓存 {v['cached']}），累计 {v['seconds']:.0f} s"
                for k, v in src.items()) + "。累计秒数是各并发请求耗时之和，不是墙钟。")
    L.append("")
    pairs = {}
    for r in runs:
        pairs.setdefault(r["tag"], {})[r["phase"]] = r
    for tag, d in pairs.items():
        if "cold" in d and "warm" in d and d["warm"]["wall_s"]:
            L.append(f"- {tag}：冷启动 {d['cold']['wall_s']} s，热缓存 {d['warm']['wall_s']} s，"
                     f"加速 {d['cold']['wall_s'] / d['warm']['wall_s']:.1f} 倍。")
    L.append("")

    # ---- per-paper cost from the cold runs, and the standard paper
    cold = [r for r in runs if r["phase"] == "cold"]
    if cold:
        L += ["## 3. 冷启动单篇实际花费", "",
              "| 运行 | 任务 | 调用 | 输入 token | 输出 token | 元 |", "| --- | --- | --- | --- | --- | --- |"]
        for r in cold:
            total = 0.0
            for task, v in sorted(r["tasks"].items()):
                key = ("embed" if task == "embed" else "rerank" if task == "rerank"
                       else "qwen3.8-max" if any("max" in m for m in v["models"]) else "qwen3.8-flash")
                # local route (mlx / OpenVINO): model names are not cloud Qwen ids, cost 0
                local = task not in ("embed", "rerank") and not any(
                    m.startswith("qwen") for m in v["models"])
                y = 0.0 if local else _cost(key, v["prompt"], v["completion"])
                total += y
                L.append(f"| {r['tag']} | {task} | {v['calls']} | {v['prompt']} | {v['completion']} | {y:.3f} |")
            L.append(f"| {r['tag']} | 合计 | | | | **{total:.2f}** |")
        L.append("")

        # per-unit rates from the cold runs -> standard paper
        unit = {"structure": "references", "extract": "paragraphs", "typo": "paragraphs",
                "function": "claims", "judge": "support_checks", "review": "support_checks",
                "embed": "linked_pdfs", "rerank": "support_checks"}
        rates: dict[str, list[float]] = defaultdict(list)
        toks: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for r in cold:
            for task, u in unit.items():
                v = r["tasks"].get(task)
                if not v or not r["size"][u]:
                    continue
                rates[task].append(v["calls"] / r["size"][u])
                toks[task].append((v["prompt"] / v["calls"], v["completion"] / v["calls"]))
        std = {"references": 35, "markers": 65, "paragraphs": 40, "claims": 55, "support_checks": 75,
               "linked_pdfs": 35}
        L += ["## 4. 标准论文的冷启动成本", "",
              f"标准论文：参考文献 {std['references']} 条、正文引用 {std['markers']} 处、正文段落 "
              f"{std['paragraphs']} 个、论断 {std['claims']} 条、论断与文献配对 {std['support_checks']} 个，"
              f"被引全文 {std['linked_pdfs']} 篇都能拿到（向量按全文计，偏保守）。"
              "每个任务的调用频次按冷启动实测的「调用数 ÷ 对应规模」取平均后折算，单次 token 取实测平均。", ""]
        rows = []
        for task, u in unit.items():
            if not rates.get(task):
                continue
            n = statistics.mean(rates[task]) * std[u]
            p = statistics.mean(t[0] for t in toks[task])
            c = statistics.mean(t[1] for t in toks[task])
            rows.append((task, u, n, p, c))
        L += ["| 任务 | 频次依据 | 次数 | 单次输入 | 单次输出 | 配置 A 元 | 配置 B 元（复核触发 25%–35%） |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
        tot_a = 0.0
        tot_b = [0.0, 0.0]
        pairs_n = std["support_checks"]
        for task, u, n, p, c in rows:
            key = task if task in ("embed", "rerank") else "qwen3.8-flash"
            a = n * _cost(key, p, c)
            if task == "review":
                # B: review is triggered for 25%-35% of judged pairs and runs on max
                b = [pairs_n * f * _cost("qwen3.8-max", p, c) for f in (0.25, 0.35)]
                L.append(f"| {task} | {u} | {n:.0f} | {p:.0f} | {c:.0f} | {a:.3f} | "
                         f"{b[0]:.3f}–{b[1]:.3f} |")
            else:
                b = [a, a]
                L.append(f"| {task} | {u} | {n:.0f} | {p:.0f} | {c:.0f} | {a:.3f} | {a:.3f} |")
            tot_a += a
            tot_b = [tot_b[0] + b[0], tot_b[1] + b[1]]
        L.append(f"| 合计 | | | | | **{tot_a:.2f}** | **{tot_b[0]:.2f}–{tot_b[1]:.2f}** |")
        emb = sum(n * p for t, _, n, p, _ in rows if t in ("embed", "rerank"))
        sf = emb / 1e6 * 0.14
        L.append(f"| 向量与重排换成硅基流动（约 0.14 元/百万 token，开发机配置） | | | | | "
                 f"**{tot_a - emb / 1e6 * 0.5 + sf:.2f}** | "
                 f"**{tot_b[0] - emb / 1e6 * 0.5 + sf:.2f}–{tot_b[1] - emb / 1e6 * 0.5 + sf:.2f}** |")
        obs = [(r["tag"], r["tasks"].get("review", {}).get("calls", 0) / max(r["size"]["support_checks"], 1),
                r["tasks"].get("judge", {}).get("calls", 0) / max(r["size"]["support_checks"], 1))
               for r in cold]
        L += ["", "实测复核触发率（复核调用 ÷ 论断与文献配对）：" +
              "；".join(f"{t} {x:.0%}（每对首轮判断类调用 {j:.1f} 次，含细节复查与检索词）"
                       for t, x, j in obs) + "。配置 B 的 25%–35% 也按配对数计。", "",
              "配置 A：所有对话任务用 qwen3.8-flash，加百炼向量与重排。配置 B：首轮判断用 flash，"
              "复核改用 qwen3.8-max，按论断与文献配对数的 25%–35% 触发。期刊对标（profile、overview）"
              "只在填写目标期刊时运行，不计入上表。"]

    text = "\n".join(L) + "\n"
    (HERE / "results" / "cost_speed.md").write_text(text, "utf-8")
    print(text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("input")
    r.add_argument("library", nargs="?")
    r.add_argument("--tag", required=True)
    r.add_argument("--cache", required=True)
    r.add_argument("--save", help="also write the report JSON here (stays local)")
    sp.add_parser("report")
    args = ap.parse_args()
    return cmd_run(args) if args.cmd == "run" else cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
