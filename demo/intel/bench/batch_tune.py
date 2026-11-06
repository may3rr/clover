"""Continuous-batching parameter sweep for GPU 8B.

For each (cache_size, max_num_seqs), submit 16 requests of ~1315 prompt
tokens / 128 new tokens and record throughput, latency, peak RSS and lowest
available memory. Then compare prefix caching on/off with a shared ~600-token
prefix.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import threading
import time
from pathlib import Path

import psutil

BASE = ("Academic citation verification requires checking whether each cited reference "
        "actually supports the claim it is attached to, whether the reported numbers and "
        "datasets match the source, and whether the cited work is about the same task. ")


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


def build_text(tok, target: int, tail_sentence: str = "") -> str:
    text = (BASE + tail_sentence) * 60
    for _ in range(40):
        prompt = tok.apply_chat_template([{"role": "user", "content": text}], True,
                                         extra_context={"enable_thinking": False})
        n = int(tok.encode(prompt).input_ids.shape[-1])
        if target - 20 <= n <= target + 20:
            return prompt
        if n > target + 20:
            text = text[: int(len(text) * 0.94)]
        else:
            text += BASE
    return prompt


def run_case(g, model, tok, cache_dir, cache_size, max_seqs, prompts, gen_cfg, prefix=False):
    sched = g.SchedulerConfig()
    sched.max_num_seqs = max_seqs
    try:
        sched.max_num_batched_tokens = 32768
    except Exception:
        pass
    try:
        sched.cache_size = cache_size
    except Exception:
        pass
    try:
        sched.enable_prefix_caching = prefix
    except Exception:
        pass
    props = {"CACHE_DIR": cache_dir, "PERFORMANCE_HINT": "THROUGHPUT"}
    t0 = time.perf_counter()
    pipe = g.ContinuousBatchingPipeline(model, sched, "GPU", props)
    load_s = time.perf_counter() - t0
    with Sampler() as mem:
        t1 = time.perf_counter()
        try:
            pipe.generate(prompts, [gen_cfg] * len(prompts))
            total_s = time.perf_counter() - t1
            ok = True
            err = None
        except Exception as e:  # noqa: BLE001
            total_s = time.perf_counter() - t1
            ok = False
            err = str(e)[:600]
    del pipe
    gc.collect()
    n = len(prompts)
    tokens = n * gen_cfg.max_new_tokens
    return {
        "cache_size": cache_size, "max_num_seqs": max_seqs, "prefix_caching": prefix,
        "requests": n, "ok": ok, "error": err,
        "load_s": round(load_s, 1), "total_s": round(total_s, 2),
        "avg_per_request_s": round(total_s / n, 2) if ok else None,
        "throughput_tok_s": round(tokens / total_s, 1) if ok else None,
        "peak_rss_gb": round(mem.peak / 1024**3, 2),
        "min_available_gb": round(mem.min_avail / 1024**3, 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=r"C:\clover-models\Qwen3-8B-int4-ov")
    ap.add_argument("--cache", default=r"C:\clover-models\.openvino_cache")
    ap.add_argument("--cache-sizes", default="2,4,6")
    ap.add_argument("--max-seqs", default="8,12,16")
    ap.add_argument("--requests", type=int, default=16)
    ap.add_argument("--out", default=r"C:\clover\demo\intel\bench\batch-tune.json")
    a = ap.parse_args()

    import openvino_genai as g

    os.makedirs(a.cache, exist_ok=True)
    tok = g.Tokenizer(a.model)
    prompt = build_text(tok, 1315)
    gen_cfg = g.GenerationConfig()
    gen_cfg.max_new_tokens = 128
    gen_cfg.do_sample = False
    gen_cfg.ignore_eos = True

    report = {"model": a.model, "requests": a.requests,
              "prompt_tokens": int(tok.encode(prompt).input_ids.shape[-1]),
              "cases": [], "prefix": []}

    for cs in [float(x) for x in a.cache_sizes.split(",")]:
        for ms in [int(x) for x in a.max_seqs.split(",")]:
            print(f"cache_size={cs} max_num_seqs={ms} ...", flush=True)
            row = run_case(g, a.model, tok, a.cache, cs, ms, [prompt] * a.requests, gen_cfg)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            report["cases"].append(row)

    best = max([r for r in report["cases"] if r["ok"] and r["peak_rss_gb"] <= 10],
               key=lambda r: r["throughput_tok_s"], default=None)
    if best:
        report["best_under_10gb"] = best
        cs, ms = best["cache_size"], best["max_num_seqs"]
        prefix_text = build_text(tok, 600, "Shared template sentence. ")

        def make_prompts(shared: bool):
            out = []
            for i in range(a.requests):
                if shared:
                    out.append(prefix_text + f" Case number {i}. " + BASE * 6)
                else:
                    out.append(build_text(tok, 1315, f"Case number {i}. "))
            return out

        for mode in (False, True):
            prompts = make_prompts(mode)
            print(f"prefix_caching={mode} cache_size={cs} max_num_seqs={ms} ...", flush=True)
            row = run_case(g, a.model, tok, a.cache, cs, ms, prompts, gen_cfg, prefix=mode)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            report["prefix"].append(row)

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", a.out, flush=True)


if __name__ == "__main__":
    main()
