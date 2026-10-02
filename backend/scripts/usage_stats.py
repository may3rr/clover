"""Print the persistent LLM usage log, aggregated by day + provider + model.

Usage:  python -m scripts.usage_stats [--by-task] [--db PATH]
The log lives in the same SQLite file as the KV cache (llm_usage table),
populated by citecheck.llm.client on every real call and cache hit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citecheck.cache import Cache  # noqa: E402
from citecheck.config import get_settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="sqlite path (default: configured cache)")
    ap.add_argument("--by-task", action="store_true",
                    help="also break down per task within each model")
    ap.add_argument("--day", default=None, help="only this day, e.g. 2026-10-05")
    args = ap.parse_args()

    db = Path(args.db).expanduser() if args.db else get_settings().cache_path
    if not db.exists():
        print(f"数据库不存在：{db}")
        return 1

    conn = Cache(db)._conn  # opening via Cache creates llm_usage if absent
    where = "WHERE date(ts) = ?" if args.day else ""
    params = (args.day,) if args.day else ()

    group = "date(ts), provider, model" + (", task" if args.by_task else "")
    rows = conn.execute(
        f"SELECT {group}, COUNT(*), SUM(cached), "
        f"SUM(prompt_tokens), SUM(completion_tokens) "
        f"FROM llm_usage {where} GROUP BY {group} ORDER BY {group}",
        params,
    ).fetchall()

    if not rows:
        print("还没有 LLM 调用记录。")
        return 0

    header = (["日期", "供应商", "模型"] + (["任务"] if args.by_task else [])
              + ["调用", "其中缓存", "输入 tok", "输出 tok"])
    data = [[str(c) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in data)) for i, h in enumerate(header)]
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    print("  ".join("-" * w for w in widths))
    tot_calls = tot_cached = tot_in = tot_out = 0
    for r in rows:
        *keys, calls, cached, pin, pout = r
        print("  ".join(str(k).ljust(w) for k, w in zip(keys, widths))
              + "  " + "  ".join(str(v).rjust(w) for v, w in
                               zip((calls, cached, pin, pout), widths[len(keys):])))
        tot_calls += calls
        tot_cached += cached or 0
        tot_in += pin or 0
        tot_out += pout or 0
    print("  ".join("-" * w for w in widths))
    print(f"合计  调用 {tot_calls}（缓存 {tot_cached}）  "
          f"输入 {tot_in} tok  输出 {tot_out} tok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
