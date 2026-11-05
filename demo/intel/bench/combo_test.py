"""Three-way contention test.

Solo baselines (30 s each):
  - GPU 8B judge
  - NPU 8B-cw extract
  - NPU embedding, 24 windows per call

Then 180 s with all three looping concurrently. Reports calls/s, average
latency, slowdown vs solo, early/late rate (thermal), and peak memory.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
CLOVER = HERE.parents[2]
sys.path.insert(0, str(CLOVER / "backend"))

from citecheck.llm import ov  # noqa: E402
from citecheck.support.claims import _PROMPT as EXTRACT_PROMPT  # noqa: E402
from citecheck.support.judge import _PROMPT as JUDGE_PROMPT  # noqa: E402

WINDOWS = [
    "We present a residual learning framework to ease the training of networks that are substantially deeper than those used previously.",
    "Training Deep Neural Networks is complicated by the fact that the distribution of each layer's inputs changes during training.",
    "We propose a method to jointly train on object detection and classification.",
    "批归一化将每一层的输入规范化为零均值单位方差，使得网络可以使用更高的学习率，训练收敛更快。",
    "The PASCAL Visual Object Classes challenge is a benchmark in visual object category recognition and detection.",
    "Product quantization decomposes the space into a Cartesian product of low dimensional subspaces and quantizes each subspace separately.",
] * 4

JUDGE_MSG = JUDGE_PROMPT.format(
    claim="We adopt Faster R-CNN, which runs at 5 frames per second on a GPU, as our detection baseline.",
    sentence_line="", entry_line="", cocited_line="",
    title="Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks",
    excerpt=("We propose a Region Proposal Network (RPN) that shares full-image convolutional features "
             "with the detection network. Our detection system runs at 5 frames per second on a GPU."))
EXTRACT_MSG = EXTRACT_PROMPT.format(
    sentence="We adopt Faster R-CNN ⟦m1⟧, which runs at 5 frames per second on a GPU, as our detection baseline.")


class Sampler:
    def __init__(self):
        self.proc = psutil.Process()
        self.peak = 0
        self.min_avail = psutil.virtual_memory().available
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.peak = max(self.peak, self.proc.memory_info().rss)
                self.min_avail = min(self.min_avail, psutil.virtual_memory().available)
            except Exception:
                pass
            time.sleep(0.2)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join(timeout=2)


def bench(fn, seconds: float) -> dict:
    times = []
    errors = []
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        t0 = time.perf_counter()
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            errors.append(str(e)[:300])
            break
        times.append(time.perf_counter() - t0)
    total = sum(times)
    half = len(times) // 2
    early = (half / sum(times[:half])) if half and sum(times[:half]) else None
    late = (half / sum(times[half:])) if half and sum(times[half:]) else None
    return {
        "calls": len(times), "seconds": round(seconds, 1),
        "calls_per_s": round(len(times) / total, 3) if total else None,
        "avg_latency_s": round(total / len(times), 3) if times else None,
        "early_calls_per_s": round(early, 3) if early else None,
        "late_calls_per_s": round(late, 3) if late else None,
        "errors": errors,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu-model", default=r"C:\clover-models\Qwen3-8B-int4-ov")
    ap.add_argument("--npu-model", default=r"C:\clover-models\Qwen3-8B-int4-cw-ov")
    ap.add_argument("--embed-model", default=r"C:\clover-models\Qwen3-Embedding-0.6B-int8-ov")
    ap.add_argument("--gpu-cache", default=r"C:\clover-models\.openvino_cache")
    ap.add_argument("--npu-cache", default=r"C:\clover-models\.ov_cache_npu\len2048")
    ap.add_argument("--solo-s", type=float, default=30)
    ap.add_argument("--combo-s", type=float, default=180)
    ap.add_argument("--out", default=r"C:\clover\demo\intel\bench\combo.json")
    a = ap.parse_args()

    print("loading models ...", flush=True)
    t0 = time.perf_counter()
    gpu = ov.Generator(a.gpu_model, "GPU", 2048, 256, a.gpu_cache)
    npu = ov.Generator(a.npu_model, "NPU", 2048, 256, a.npu_cache)
    emb = ov.Embedder(a.embed_model, "NPU", 512, a.npu_cache)
    print(f"loaded in {time.perf_counter()-t0:.1f}s: GPU={gpu.device} NPU={npu.device} EMB={emb.device}", flush=True)

    def judge():
        gpu.generate([{"role": "user", "content": JUDGE_MSG}], 256)

    def extract():
        npu.generate([{"role": "user", "content": EXTRACT_MSG}], 256)

    def embed():
        emb.embed(WINDOWS)

    report = {"models": {"gpu": a.gpu_model, "npu": a.npu_model, "embed": a.embed_model},
              "solo_s": a.solo_s, "combo_s": a.combo_s}

    print("solo judge ...", flush=True)
    report["solo_judge"] = bench(judge, a.solo_s)
    print(json.dumps(report["solo_judge"]), flush=True)
    print("solo extract ...", flush=True)
    report["solo_extract"] = bench(extract, a.solo_s)
    print(json.dumps(report["solo_extract"]), flush=True)
    print("solo embed ...", flush=True)
    report["solo_embed"] = bench(embed, a.solo_s)
    print(json.dumps(report["solo_embed"]), flush=True)

    print("combo 3-way ...", flush=True)
    results = {}

    def runner(name, fn):
        results[name] = bench(fn, a.combo_s)

    with Sampler() as mem:
        threads = [threading.Thread(target=runner, args=(n, f))
                   for n, f in (("judge", judge), ("extract", extract), ("embed", embed))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        report["combo_peak_rss_gb"] = round(mem.peak / 1024**3, 2)
        report["combo_min_available_gb"] = round(mem.min_avail / 1024**3, 2)

    report["combo"] = results
    for k, v in results.items():
        solo = report.get("solo_" + k)
        if solo and v.get("avg_latency_s") and solo.get("avg_latency_s"):
            v["slowdown_vs_solo"] = round(v["avg_latency_s"] / solo["avg_latency_s"], 2)
    print(json.dumps(report, ensure_ascii=False, indent=1), flush=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", a.out, flush=True)


if __name__ == "__main__":
    main()
