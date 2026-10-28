"""Orig alarms of one or more runs, split by the hand audit labels.

    python audit_stats.py [--clean] RUN [RUN ...]

R real error in the manuscript, F false alarm, C PDF-to-docx conversion
artifact, U cannot tell. Labels come from orig_alarm_audit_full.json; an
alarm with no label is listed so it can be audited.

--clean drops every item (orig, swap and alter) whose claim is listed in
excluded_claims.json: claims the F12 parse fix no longer produces, and
claims hand-audited as conversion artifacts. The orig false alarm rate is
then F / (orig items kept).
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
EXCLUDED = HERE / "excluded_claims.json"


def main() -> int:
    args = sys.argv[1:]
    clean = "--clean" in args
    runs = [a for a in args if a != "--clean"]
    items = {i["id"]: i for i in bench._load(bench.ITEMS)}
    if clean:
        drop = set(json.loads(EXCLUDED.read_text()))
        items = {k: i for k, i in items.items()
                 if f"{i['paper']}:{i['claim_id']}" not in drop}
    audit = json.loads(AUDIT.read_text())
    n_orig = sum(1 for i in items.values() if i["kind"] == "orig")
    if clean:
        print(f"干净子集：orig {n_orig} 条")
    print("| run | orig 报警 | R | F | C | U | 去掉 C 后 R 占比 | swap 检出 | alter 检出 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for run in runs:
        rows = bench._rows(run)
        hit = {k for k, r in rows.items() if r["flag"] and k in items}
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
