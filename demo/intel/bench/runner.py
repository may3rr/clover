"""Run one probe (kind, device) and write its row as JSON.

Used by probe_timeout.py so that a stuck NPU compilation can be killed
without losing the rest of the results.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEL = HERE.parent
CLOVER = HERE.parents[2]

spec = importlib.util.spec_from_file_location("probe", str(INTEL / "probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True, choices=["embed", "rerank", "llm"])
    ap.add_argument("--path", required=True)
    ap.add_argument("--device", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--vecs-in", default="")
    ap.add_argument("--vecs-out", default="")
    a = ap.parse_args()

    ref = None
    if a.vecs_in:
        import numpy as np
        ref = np.load(a.vecs_in)

    if a.kind == "embed":
        row = probe.probe_embed(a.path, a.device, a.cache, ref)
        if a.vecs_out:
            import numpy as np
            np.save(a.vecs_out, row.pop("_vecs"))
    elif a.kind == "rerank":
        row = probe.probe_rerank(a.path, a.device, a.cache)
    else:
        row = probe.probe_llm(a.path, a.device, a.cache)

    row["ok"] = True
    Path(a.out).write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
