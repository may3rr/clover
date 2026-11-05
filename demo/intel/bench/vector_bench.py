"""Vector throughput over 6000 windows.

Solo: NPU / CPU / GPU at batch 8, 24, 64.
Combined: NPU + CPU, half the windows each.
Busy: GPU 8B continuous batching (16 concurrent judge) + NPU/CPU vectors.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
CLOVER = HERE.parents[2]
sys.path.insert(0, str(CLOVER / "backend"))

import openvino_genai as g  # noqa: E402

WINDOWS = [
    "We present a residual learning framework to ease the training of networks that are substantially deeper than those used previously. We explicitly reformulate the layers as learning residual functions with reference to the layer inputs.",
    "Training Deep Neural Networks is complicated by the fact that the distribution of each layer's inputs changes during training. We refer to this phenomenon as internal covariate shift, and address the problem by normalizing layer inputs.",
    "We propose a method to jointly train on object detection and classification. Using this method we train YOLO9000 simultaneously on the COCO detection dataset and the ImageNet classification dataset.",
    "批归一化将每一层的输入规范化为零均值单位方差，使得网络可以使用更高的学习率，训练收敛更快。",
    "The PASCAL Visual Object Classes challenge is a benchmark in visual object category recognition and detection, providing the vision community with a standard dataset of images and annotation.",
    "Product quantization decomposes the space into a Cartesian product of low dimensional subspaces and quantizes each subspace separately.",
]

JUDGE = ("Academic citation verification requires checking whether each cited reference actually "
         "supports the claim it is attached to, whether the reported numbers and datasets match "
         "the source, and whether the cited work is about the same task. ") * 25


def make_texts(tok, n: int) -> list[str]:
    out = []
    i = 0
    while len(out) < n:
        t = WINDOWS[i % len(WINDOWS)]
        j = 1
        while int(tok.encode(t).input_ids.shape[-1]) < 220:
            t += " " + WINDOWS[(i + j) % len(WINDOWS)]
            j += 1
        # trim very long ones by sentence boundaries
        while int(tok.encode(t).input_ids.shape[-1]) > 380 and j > 1:
            j -= 1
            t = WINDOWS[i % len(WINDOWS)] + "".join(" " + WINDOWS[(i + k) % len(WINDOWS)] for k in range(1, j + 1))
        out.append(t)
        i += 1
    return out


def make_pipe(embed_model, device, batch, cache):
    cfg = g.TextEmbeddingPipeline.Config()
    cfg.pooling_type = g.TextEmbeddingPipeline.PoolingType.LAST_TOKEN
    cfg.normalize = True
    cfg.padding_side = "left"
    cfg.max_length = 512
    if device == "NPU":
        # fixed shape only; batch>1 aborts the compiler
        cfg.batch_size = 1
        cfg.pad_to_max_length = True
    # do not set cfg.batch_size for CPU/GPU: the static-batch path is ~12x
    # slower and requires exactly batch_size texts; chunking is enough
    return g.TextEmbeddingPipeline(embed_model, device, cfg, CACHE_DIR=cache)


def embed_all(pipe, texts, batch):
    t0 = time.perf_counter()
    for i in range(0, len(texts), batch):
        pipe.embed_documents(texts[i:i + batch])
    return time.perf_counter() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed-model", default=r"C:\clover-models\Qwen3-Embedding-0.6B-int8-ov")
    ap.add_argument("--llm-model", default=r"C:\clover-models\Qwen3-8B-int4-ov")
    ap.add_argument("--cache", default=r"C:\clover-models\.openvino_cache")
    ap.add_argument("--n", type=int, default=6000)
    ap.add_argument("--batches", default="8,24,64")
    ap.add_argument("--out", default=r"C:\clover\demo\intel\bench\vector.json")
    ap.add_argument("--devices", default="NPU,CPU,GPU")
    ap.add_argument("--npu-batch", type=int, default=1)
    ap.add_argument("--cpu-batch", type=int, default=64)
    ap.add_argument("--skip-solo", action="store_true")
    ap.add_argument("--skip-split", action="store_true")
    ap.add_argument("--skip-busy", action="store_true")
    ap.add_argument("--one", default="", help="child mode: DEVICE:BATCH")
    ap.add_argument("--one-out", default="")
    ap.add_argument("--case-timeout", type=int, default=1200)
    a = ap.parse_args()

    if a.one:
        dev, batch = a.one.split(":")
        batch = int(batch)
        tok = g.Tokenizer(a.embed_model)
        texts = make_texts(tok, a.n)
        try:
            t0 = time.perf_counter()
            pipe = make_pipe(a.embed_model, dev, batch, a.cache)
            load = time.perf_counter() - t0
            dt = embed_all(pipe, texts, batch)
            row = {"device": dev, "batch": batch, "ok": True,
                   "load_s": round(load, 1), "total_s": round(dt, 1),
                   "windows_s": round(a.n / dt, 1)}
        except BaseException as e:  # noqa: BLE001 — LLVM abort may kill us
            row = {"device": dev, "batch": batch, "ok": False, "error": str(e)[:500]}
        Path(a.one_out).write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        return

    tok = g.Tokenizer(a.embed_model)
    texts = make_texts(tok, a.n)
    lens = [int(tok.encode(t).input_ids.shape[-1]) for t in texts[:200]]
    report = {"n": a.n, "text_token_range": [min(lens), max(lens)], "solo": [], "split": None, "busy": None}

    def run_child(dev: str, batch: int) -> dict:
        out = Path(a.out).with_name(f"vector-one-{dev}-{batch}.json")
        cmd = [sys.executable, str(Path(__file__)), "--one", f"{dev}:{batch}",
               "--one-out", str(out), "--n", str(a.n),
               "--embed-model", a.embed_model, "--cache", a.cache]
        try:
            p = subprocess.run(cmd, timeout=a.case_timeout, capture_output=True, text=True)
            if out.exists():
                return json.loads(out.read_text(encoding="utf-8"))
            tail = ((p.stderr or "") + (p.stdout or ""))[-500:]
            return {"device": dev, "batch": batch, "ok": False, "error": tail}
        except subprocess.TimeoutExpired:
            return {"device": dev, "batch": batch, "ok": False,
                    "error": f"timeout {a.case_timeout}s"}

    if not a.skip_solo:
        for dev in [d.strip().upper() for d in a.devices.split(",") if d.strip()]:
            if dev == "NPU":
                # batch>1 aborts the VPUX compiler (LLVM ERROR), so only the
                # fixed-shape batch=1 pipeline is testable
                for fail_b in (8, 24, 64):
                    report["solo"].append({
                        "device": "NPU", "batch": fail_b, "ok": False,
                        "error": ("NPU TextEmbeddingPipeline batch>1 aborts in the compiler: "
                                  "LLVM ERROR: Failed to infer result type(s): "
                                  "\"IE.Add\"(tensor<1x128x512x512xf32>, tensor<1x64x512x512xf32>)")})
                batches = [1]
            else:
                batches = [int(x) for x in a.batches.split(",")]
            for b in batches:
                print(f"solo {dev} batch={b} ...", flush=True)
                row = run_child(dev, b)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                report["solo"].append(row)

    def best(dev):
        ok = [r for r in report["solo"] if r["device"] == dev and r["ok"]]
        return max(ok, key=lambda r: r["windows_s"]) if ok else None

    npu_best = best("NPU") or {"batch": a.npu_batch}
    cpu_best = best("CPU") or {"batch": a.cpu_batch}
    if not a.skip_split:
        print(f"split NPU(batch={npu_best['batch']}) + CPU(batch={cpu_best['batch']}) ...", flush=True)
        p1 = make_pipe(a.embed_model, "NPU", npu_best["batch"], a.cache)
        p2 = make_pipe(a.embed_model, "CPU", cpu_best["batch"], a.cache)
        half = a.n // 2
        result = {}

        def run(name, pipe, part, b):
            t0 = time.perf_counter()
            embed_all(pipe, part, b)
            result[name] = {"total_s": round(time.perf_counter() - t0, 1),
                            "windows_s": round(len(part) / (time.perf_counter() - t0), 1)}

        t0 = time.perf_counter()
        th = [threading.Thread(target=run, args=("NPU", p1, texts[:half], npu_best["batch"])),
              threading.Thread(target=run, args=("CPU", p2, texts[half:], cpu_best["batch"]))]
        for t in th:
            t.start()
        for t in th:
            t.join()
        wall = time.perf_counter() - t0
        report["split"] = {"wall_s": round(wall, 1), "windows_s": round(a.n / wall, 1), **result}
        print(json.dumps(report["split"], ensure_ascii=False), flush=True)

        # busy: GPU 8B CB + NPU/CPU vectors
        print("busy: GPU 8B CB(16) + NPU/CPU vectors ...", flush=True)
        sched = g.SchedulerConfig()
        sched.max_num_seqs = 16
        try:
            sched.max_num_batched_tokens = 32768
            sched.cache_size = 2
            sched.enable_prefix_caching = False
        except Exception:
            pass
        cb = g.ContinuousBatchingPipeline(a.llm_model, sched, "GPU",
                                          {"CACHE_DIR": a.cache, "PERFORMANCE_HINT": "THROUGHPUT"})
        cfg = g.GenerationConfig()
        cfg.max_new_tokens = 128
        cfg.do_sample = False
        cfg.ignore_eos = True
        prompts = [JUDGE] * 16
        stop = threading.Event()
        gpu_count = {"batches": 0}

        def gpu_loop():
            while not stop.is_set():
                try:
                    cb.generate(prompts, [cfg] * 16)
                    gpu_count["batches"] += 1
                except Exception as e:  # noqa: BLE001
                    gpu_count["error"] = str(e)[:400]
                    break

        gt = threading.Thread(target=gpu_loop, daemon=True)
        gt.start()
        result2 = {}

        def run2(name, pipe, part, b):
            t0 = time.perf_counter()
            embed_all(pipe, part, b)
            result2[name] = {"total_s": round(time.perf_counter() - t0, 1),
                             "windows_s": round(len(part) / (time.perf_counter() - t0), 1)}

        t0 = time.perf_counter()
        th = [threading.Thread(target=run2, args=("NPU", p1, texts[:half], npu_best["batch"])),
              threading.Thread(target=run2, args=("CPU", p2, texts[half:], cpu_best["batch"]))]
        for t in th:
            t.start()
        for t in th:
            t.join()
        wall2 = time.perf_counter() - t0
        stop.set()
        gt.join(timeout=60)
        report["busy"] = {"wall_s": round(wall2, 1), "windows_s": round(a.n / wall2, 1),
                          "gpu_batches": gpu_count["batches"],
                          "gpu_tokens": gpu_count["batches"] * 16 * 128,
                          "gpu_error": gpu_count.get("error"), **result2}
        print(json.dumps(report["busy"], ensure_ascii=False), flush=True)

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", a.out, flush=True)


if __name__ == "__main__":
    main()
