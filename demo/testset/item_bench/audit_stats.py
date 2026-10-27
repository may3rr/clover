"""Orig alarms of one or more runs, split by the hand audit labels.

    python audit_stats.py RUN [RUN ...]

R real error in the manuscript, F false alarm, C PDF-to-docx conversion
artifact, U cannot tell. Labels come from orig_alarm_audit_full.json; an
alarm with no label is listed so it can be audited.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bench  # noqa: E402

AUDIT = HERE / "orig_alarm_audit_full.json"


def main() -> int:
    items = {i["id"]: i for i in bench._load(bench.ITEMS)}
    audit = json.loads(AUDIT.read_text())
    print("| run | orig 报警 | R | F | C | U | 去掉 C 后 R 占比 | swap 检出 | alter 检出 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for run in sys.argv[1:]:
        rows = bench._rows(run)
        hit = {k for k, r in rows.items() if r["flag"]}
        orig = sorted(k for k in hit if items[k]["kind"] == "orig")
        missing = [k for k in orig if k not in audit]
        c = Counter(audit[k]["label"] for k in orig if k in audit)
        kept = c["R"] + c["F"] + c["U"]
        n = {kind: sum(1 for i in items.values() if i["kind"] == kind)
             for kind in ("swap", "alter")}
        det = {kind: sum(1 for k in hit if items[k]["kind"] == kind)
               for kind in ("swap", "alter")}
        print(f"| {run} | {len(orig)} | {c['R']} | {c['F']} | {c['C']} | "
              f"{c['U']} | {c['R'] / kept:.2f} | "
              f"{det['swap']}/{n['swap']} | {det['alter']}/{n['alter']} |")
        for k in missing:
            print("  未核对:", k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
