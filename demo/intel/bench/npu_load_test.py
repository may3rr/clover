"""Cold/warm load test with a hard wall-clock budget.

Runs npu_runner.py in a child process so a stuck NPU compilation can be killed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_load(model: str, cache: str, max_prompt_len: int, timeout_s: int, out: Path) -> dict:
    row_file = out.with_suffix(".row.json")
    cmd = [sys.executable, str(HERE / "npu_runner.py"),
           "--model", model, "--device", "NPU", "--cache", cache,
           "--max-prompt-len", str(max_prompt_len), "--mode", "load",
           "--out", str(row_file)]
    t0 = time.perf_counter()
    try:
        subprocess.run(cmd, check=True, timeout=timeout_s,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout_s}s", "wall_s": timeout_s}
    except subprocess.CalledProcessError as e:
        msg = (e.stdout or b"").decode("utf-8", "replace")[-1500:]
        return {"ok": False, "error": msg or f"exit {e.returncode}",
                "wall_s": round(time.perf_counter() - t0, 1)}
    if not row_file.exists():
        return {"ok": False, "error": "no row written", "wall_s": round(time.perf_counter() - t0, 1)}
    row = json.loads(row_file.read_text(encoding="utf-8"))
    row["wall_s"] = round(time.perf_counter() - t0, 1)
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--cache-root", default=r"C:\clover-models\.ov_cache_npu")
    ap.add_argument("--max-prompt-len", type=int, default=2048)
    ap.add_argument("--timeout-s", type=int, default=1800)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    cache = str(Path(a.cache_root) / f"len{a.max_prompt_len}")
    if Path(cache).exists():
        shutil.rmtree(cache, ignore_errors=True)
    Path(cache).mkdir(parents=True, exist_ok=True)

    report = {"model": a.model, "max_prompt_len": a.max_prompt_len,
              "cold_budget_s": a.timeout_s, "cache": cache}

    print("cold load ...", flush=True)
    cold = run_load(a.model, cache, a.max_prompt_len, a.timeout_s, Path(a.out))
    report["cold"] = cold
    print(json.dumps(cold, ensure_ascii=False), flush=True)

    if cold.get("ok"):
        print("warm load ...", flush=True)
        warm = run_load(a.model, cache, a.max_prompt_len, min(a.timeout_s, 900), Path(a.out))
        report["warm"] = warm
        print(json.dumps(warm, ensure_ascii=False), flush=True)

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", a.out, flush=True)


if __name__ == "__main__":
    main()
