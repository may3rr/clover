"""T3: run the labelled judge pairs through the local engine only.

Reuses the "current" variant from demo/testset/judge_ab.py: J._PROMPT with
the focused sentence, entry and cocited lines. Forces route="local" so a
cloud key is never needed and there is no fallback.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLOVER = HERE.parents[2]
sys.path.insert(0, str(CLOVER / "backend"))

from citecheck.support import judge as J  # noqa: E402
from citecheck.support.layer import _apply_verdict  # noqa: E402

PAIRS = Path(r"C:\clover-data\judge_pairs.json")
BASELINE = HERE / "data" / "judge_cloud_flash_current.json"


async def run_pair(pair: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        t0 = time.perf_counter()
        out = None
        error = None
        try:
            out = await J.judge_claim(
                pair["claim"], pair.get("title"), pair["excerpt"],
                sentence=pair.get("focused"), entry=pair.get("entry"),
                cocited=pair.get("cocited"), template=J._PROMPT,
                route="local",
            )
        except Exception as e:  # noqa: BLE001
            error = str(e)[:300]
        dt = time.perf_counter() - t0
    row = {"id": pair["id"], "want": bool(pair["want"]), "why": pair.get("why"),
           "s": round(dt, 3), "json_ok": out is not None,
           "label": None, "off_topic": None, "flagged": None,
           "downgraded": False, "error": error}
    if out is None:
        return row
    label, _evidence, _rationale, _span = _apply_verdict(out, pair["excerpt"])
    flagged = label == "unsupported" or (
        out.off_topic and label in ("unsupported", "undetermined"))
    row.update({
        "label": label,
        "raw_label": out.label,
        "off_topic": bool(out.off_topic),
        "flagged": bool(flagged),
        "downgraded": label != out.label,
    })
    return row


async def main_async(a: argparse.Namespace) -> None:
    pairs = json.loads(Path(a.pairs).read_text(encoding="utf-8"))
    if a.limit:
        pairs = pairs[: a.limit]
    print(f"pairs: {len(pairs)}", flush=True)
    sem = asyncio.Semaphore(max(1, a.concurrency))
    t0 = time.perf_counter()
    rows = await asyncio.gather(*[run_pair(p, sem) for p in pairs])
    wall = time.perf_counter() - t0

    flags = {}
    for p, r in zip(pairs, rows):
        if r["flagged"] is not None:
            flags[f'{p["id"]}|{p["why"]}'] = bool(r["flagged"])

    def count(why: str) -> list[int]:
        total = sum(1 for p in pairs if p["why"] == why)
        hit = sum(1 for p, r in zip(pairs, rows)
                  if p["why"] == why and r["flagged"])
        return [hit, total]

    failed = sum(1 for r in rows if not r["json_ok"])
    downgraded = sum(1 for r in rows if r["downgraded"])
    report = {
        "label": a.label,
        "model": a.model,
        "device": a.device,
        "pairs": len(pairs),
        "injected": count("injected"),
        "true_issue": count("true_issue"),
        "false_alarm": count("false_alarm"),
        "failed": failed,
        "downgraded": downgraded,
        "wall_s": round(wall, 1),
        "avg_s": round(sum(r["s"] for r in rows) / len(rows), 3),
        "flags": flags,
        "items": rows,
    }

    if BASELINE.exists():
        base = json.loads(BASELINE.read_text(encoding="utf-8"))["current"]
        bflags = base.get("flags", {})
        common = [k for k in flags if k in bflags]
        agree = sum(1 for k in common if flags[k] == bflags[k])
        report["cloud"] = {
            "injected": base["injected"], "true_issue": base["true_issue"],
            "false_alarm": base["false_alarm"],
            "agreement": [agree, len(common)],
        }
        by_id = {p["id"]: p for p in pairs}
        div = []
        for k in common:
            if flags[k] != bflags[k]:
                p = by_id[k.rsplit("|", 1)[0]]
                r = next(x for x in rows if x["id"] == p["id"])
                div.append({
                    "id": p["id"], "want": p["want"], "why": p["why"],
                    "local": r["label"], "local_off_topic": r["off_topic"],
                    "cloud": (p.get("cloud") or {}).get("label"),
                    "cloud_off_topic": (p.get("cloud") or {}).get("off_topic"),
                })
        report["divergent"] = div[:12]
        report["divergent_total"] = len(div)

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("label", "injected", "true_issue", "false_alarm", "failed",
                       "downgraded", "wall_s", "avg_s")}, ensure_ascii=False), flush=True)
    if "cloud" in report:
        print("cloud:", json.dumps(report["cloud"], ensure_ascii=False), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=str(PAIRS))
    ap.add_argument("--baseline", default=str(BASELINE))
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--device", default="")
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    asyncio.run(main_async(a))


if __name__ == "__main__":
    main()
