"""Hand audit of orig alarms: show one item's context, or grep the cited PDF.

    python audit_tool.py list RUN               # ids of orig alarms in RUN
    python audit_tool.py show RUN ID [ID ...]   # claim, sentence, entry, verdict
    python audit_tool.py grep ID PATTERN        # regex over the cited PDF's full text

The verdicts go to orig_alarm_audit_full.json by hand.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bench  # noqa: E402


def _rows(run: str) -> dict[str, dict]:
    return bench._rows(run)


def _items() -> dict[str, dict]:
    return {i["id"]: i for i in bench._load(bench.ITEMS)}


def _ref_raw(paper: str, rid: str) -> str:
    for p, rep in bench._papers():
        if p == paper:
            for r in rep["references"]:
                if r["id"] == rid:
                    return r["raw"]
    return ""


def show(run: str, ids: list[str]) -> None:
    rows, items = _rows(run), _items()
    for iid in ids:
        it, r = items[iid], rows[iid]
        print(f"== {iid}  {r['label']} off_topic={r['off_topic']}")
        print("条目:", _ref_raw(it["paper"], it["ref_id"])[:300])
        print("标题:", r.get("title"))
        print("句子:", it["sentence"])
        print("论断:", it["claim"])
        print("证据:", r.get("evidence"))
        print("理由:", r["rationale"])
        print()


def grep(iid: str, pattern: str) -> None:
    from citecheck.cache import Cache
    from citecheck.config import get_settings

    it = _items()[iid]
    src = bench._Sources(Cache(get_settings().cache_path), {it["paper"]})
    pdf = src.local[(it["paper"], it["ref_id"])]
    body, _ = pdf.body()
    text = re.sub(r"\s+", " ", body)
    hits = list(re.finditer(pattern, text, re.I))
    print(f"{pdf.path.name}: {len(hits)} hits")
    for m in hits[:8]:
        print("…", text[max(0, m.start() - 200): m.end() + 200], "…\n")


def main() -> int:
    cmd = sys.argv[1]
    if cmd == "list":
        rows, items = _rows(sys.argv[2]), _items()
        for k, r in rows.items():
            if items[k]["kind"] == "orig" and r["flag"]:
                print(k)
    elif cmd == "show":
        show(sys.argv[2], sys.argv[3:])
    elif cmd == "grep":
        grep(sys.argv[2], sys.argv[3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
