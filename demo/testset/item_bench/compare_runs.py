"""Alarm changes between two runs, split by item kind and audit label.

    python compare_runs.py OLD NEW [--show KIND]

For each kind, counts the items that gained or lost an alarm. Orig items
carry their hand audit label (R/F/C/U, '-' when not audited); --show
prints every changed item of that kind with the new verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bench  # noqa: E402

AUDIT = HERE / "orig_alarm_audit_full.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--show", choices=("orig", "swap", "alter"))
    args = ap.parse_args()
    items = {i["id"]: i for i in bench._load(bench.ITEMS)}
    audit = json.loads(AUDIT.read_text())
    old, new = bench._rows(args.old), bench._rows(args.new)
    for kind in ("orig", "swap", "alter"):
        gained, lost = Counter(), Counter()
        for k, it in items.items():
            if it["kind"] != kind or k not in old or k not in new:
                continue
            a, b = old[k]["flag"], new[k]["flag"]
            lab = audit.get(k, {}).get("label", "-") if kind == "orig" else kind
            if b and not a:
                gained[lab] += 1
            elif a and not b:
                lost[lab] += 1
            if a != b and args.show == kind:
                o = new[k]
                print(f"{'+' if b else '-'} {k} [{lab}] {o['label']} ot={o['off_topic']}")
                print("   论断:", it["claim"][:120])
                print("   理由:", (o.get("rationale") or "")[:200])
        print(f"{kind}: 新增报警 {dict(gained)}，取消报警 {dict(lost)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
