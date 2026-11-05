"""probe.py with a per-(kind, device) timeout.

The stock probe.py has no timeout: on this machine Qwen3-1.7B-int4-ov compiled
on NPU for 40+ minutes without finishing, which blocks the rest of the report.
This wrapper runs each (kind, device) in a child process and records a timeout
row instead. Everything else follows probe.py exactly.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEL = HERE.parent

spec = importlib.util.spec_from_file_location("probe", str(INTEL / "probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

TIMEOUTS = {"embed": 300, "rerank": 300, "llm": 300}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=str(Path.home() / "models" / "openvino"))
    ap.add_argument("--embed", default="Qwen3-Embedding-0.6B-int8-ov")
    ap.add_argument("--rerank", default="Qwen3-Reranker-0.6B-int8-ov")
    ap.add_argument("--llm", default="Qwen3-1.7B-int4-ov")
    ap.add_argument("--only", choices=["embed", "rerank", "llm"], action="append")
    ap.add_argument("--devices", default="", help="comma list, e.g. CPU,GPU (default: all, CPU first)")
    ap.add_argument("--out", default="probe.json")
    a = ap.parse_args()

    import openvino as ov_rt
    import openvino_genai

    root = Path(a.models).expanduser()
    report: dict = {
        "machine": platform.platform(), "processor": platform.processor(),
        "python": sys.version.split()[0], "openvino": ov_rt.__version__,
        "openvino_genai": openvino_genai.__version__,
        "devices": probe._device_names(), "results": {},
        "probe_mode": "probe_timeout.py",
        "timeouts_s": TIMEOUTS,
    }
    print(json.dumps({k: report[k] for k in ("machine", "openvino", "devices")},
                     ensure_ascii=False, indent=1))
    devs = probe._devices()
    if a.devices:
        present = list(devs)
        order = []
        for want in (d.strip().upper() for d in a.devices.split(",")):
            if not want:
                continue
            for have in present:
                if (have.upper() == want or have.split(".")[0].upper() == want) and have not in order:
                    order.append(have)
                    break
        devs = order
    else:
        devs = list(reversed(devs))  # CPU first, as in probe.py
    todo = a.only or ["embed", "rerank", "llm"]
    runner = str(HERE / "runner.py")
    for kind in todo:
        path = str(root / getattr(a, kind))
        if not Path(path).is_dir():
            print(f"[{kind}] skip: missing {path}")
            continue
        rows = []
        ref_vecs = ""
        for dev in reversed(devs):
            cache = tempfile.mkdtemp(prefix=f"ovcache-{kind}-{dev}-")
            row_file = str(Path(cache) / "row.json")
            vecs_out = str(Path(cache) / "vecs.npy") if kind == "embed" else ""
            cmd = [sys.executable, runner, "--kind", kind, "--path", path,
                   "--device", dev, "--cache", cache, "--out", row_file]
            if kind == "embed" and ref_vecs:
                cmd += ["--vecs-in", ref_vecs]
            if vecs_out:
                cmd += ["--vecs-out", vecs_out]
            print(f"[{kind}] {dev} ...", flush=True)
            t0 = time.perf_counter()
            try:
                subprocess.run(cmd, check=True, timeout=TIMEOUTS[kind])
                row = json.loads(Path(row_file).read_text(encoding="utf-8"))
                if kind == "embed" and dev == "CPU" and vecs_out and Path(vecs_out).exists():
                    keep = Path(a.out).with_suffix(f".{kind}.cpu_vecs.npy")
                    shutil.copyfile(vecs_out, keep)
                    ref_vecs = str(keep)
            except subprocess.TimeoutExpired:
                row = {"device": dev, "ok": False,
                       "error": f"timeout after {TIMEOUTS[kind]}s (NPU compilation did not finish)"}
            except Exception as e:  # noqa: BLE001
                row = {"device": dev, "ok": False, "error": str(e)[:600]}
            finally:
                shutil.rmtree(cache, ignore_errors=True)
            row["wall_s"] = round(time.perf_counter() - t0, 1)
            print(json.dumps(row, ensure_ascii=False, indent=1), flush=True)
            rows.append(row)
        report["results"][kind] = rows
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written {a.out}")


if __name__ == "__main__":
    main()
