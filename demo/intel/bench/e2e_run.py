"""T4: run the real pipeline with local OpenVINO models and record memory.

Uses CITECHECK_HOME=C:\\clover-data\\e2e. Writes the report JSON plus a
sidecar with wall time, peak RSS, lowest available memory and LLM call counts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

import psutil

os.environ.setdefault("CITECHECK_HOME", r"C:\clover-data\e2e")
os.environ.setdefault("CITECHECK_CACHE", r"C:\clover-data\e2e\cache.sqlite")
CLOVER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CLOVER / "backend"))

from citecheck.pipeline import run_pipeline  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--library", default="")
    a = ap.parse_args()

    proc = psutil.Process()
    peak = {"rss": 0, "min_avail": psutil.virtual_memory().available}
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            try:
                peak["rss"] = max(peak["rss"], proc.memory_info().rss)
                peak["min_avail"] = min(peak["min_avail"], psutil.virtual_memory().available)
            except Exception:
                pass
            time.sleep(0.2)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    t0 = time.perf_counter()
    report = asyncio.run(run_pipeline(
        Path(a.src), library_dir=Path(a.library) if a.library else None))
    wall = time.perf_counter() - t0
    stop.set()
    th.join(timeout=2)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    meta = {
        "src": a.src, "out": str(out), "wall_s": round(wall, 1),
        "duration_s": report.meta.duration_s,
        "llm_calls": report.meta.llm_calls.model_dump(),
        "token_usage": report.meta.token_usage,
        "timings": report.meta.timings,
        "layers": {k: {"status": v.status, "findings": v.findings, "error": v.error}
                   for k, v in report.meta.layers.items()},
        "findings": len(report.findings),
        "peak_rss_gb": round(peak["rss"] / 1024**3, 2),
        "min_available_gb": round(peak["min_avail"] / 1024**3, 2),
    }
    out.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()
