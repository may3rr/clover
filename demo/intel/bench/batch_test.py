"""GPU continuous-batching throughput test for one OpenVINO LLM.

Measures concurrency 1/4/8/16 with ContinuousBatchingPipeline, then compares
against running the same 8 prompts one by one with LLMPipeline.

All prompts are ~1300 tokens, greedy, max 128 new tokens.
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

BASE_SENTENCE = (
    "Academic citation verification requires checking whether each cited reference "
    "actually supports the claim it is attached to, whether the reported numbers and "
    "datasets match the source, and whether the cited work is about the same task. "
)


def build_prompt(tok, target: int = 1300) -> str:
    text = BASE_SENTENCE * 60
    for _ in range(30):
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": text}], True,
            extra_context={"enable_thinking": False})
        n = int(tok.encode(prompt).input_ids.shape[-1])
        if 1260 <= n <= 1340:
            break
        if n > 1340:
            text = text[: int(len(text) * 0.92)]
        else:
            text += BASE_SENTENCE
    return prompt


class MemSampler:
    def __init__(self):
        self.proc = psutil.Process()
        self.peak_rss = 0
        self.min_avail = psutil.virtual_memory().available
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.peak_rss = max(self.peak_rss, self.proc.memory_info().rss)
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


def generated_tokens(results, fallback: int) -> int:
    total = 0
    for r in results:
        try:
            total += int(r.perf_metrics.get_num_generated_tokens())
        except Exception:
            total += fallback
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=r"C:\clover-models\Qwen3-8B-int4-ov")
    ap.add_argument("--device", default="GPU")
    ap.add_argument("--cache", default=r"C:\clover-models\.openvino_cache")
    ap.add_argument("--out", default=r"C:\clover\demo\intel\bench\batch-8b.json")
    ap.add_argument("--levels", default="1,4,8,16")
    ap.add_argument("--max-new-tokens", type=int, default=128)
    a = ap.parse_args()

    import openvino_genai as g

    os.makedirs(a.cache, exist_ok=True)
    props = {"CACHE_DIR": a.cache, "PERFORMANCE_HINT": "THROUGHPUT"}
    levels = [int(x) for x in a.levels.split(",") if x.strip()]
    report: dict = {
        "model": a.model, "device": a.device, "levels": levels,
        "max_new_tokens": a.max_new_tokens, "results": [], "sequential": None,
    }

    tok = g.Tokenizer(a.model)
    prompt = build_prompt(tok)
    ntok = int(tok.encode(prompt).input_ids.shape[-1])
    print(f"prompt tokens: {ntok}", flush=True)
    report["prompt_tokens"] = ntok

    sched = g.SchedulerConfig()
    sched.max_num_seqs = max(levels)
    try:
        sched.max_num_batched_tokens = max(32768, max(levels) * (ntok + a.max_new_tokens))
    except Exception as e:
        print("scheduler max_num_batched_tokens not settable:", e, flush=True)
    try:
        sched.enable_prefix_caching = False
    except Exception:
        pass
    try:
        sched.cache_size = 8
    except Exception as e:
        print("scheduler cache_size not settable:", e, flush=True)

    gen_cfg = g.GenerationConfig()
    gen_cfg.max_new_tokens = a.max_new_tokens
    gen_cfg.do_sample = False
    gen_cfg.ignore_eos = True  # force exactly max_new_tokens for fair throughput

    print("loading ContinuousBatchingPipeline ...", flush=True)
    t0 = time.perf_counter()
    try:
        pipe = g.ContinuousBatchingPipeline(a.model, sched, a.device, props)
    except Exception as e1:
        print("constructor form 1 failed:", e1, flush=True)
        pipe = g.ContinuousBatchingPipeline(a.model, tok, sched, a.device, **props)
    load_s = time.perf_counter() - t0
    print(f"loaded in {load_s:.1f}s", flush=True)
    report["load_s"] = round(load_s, 1)

    for n in levels:
        if psutil.virtual_memory().available < 3 * 1024**3:
            report["results"].append({"concurrency": n, "ok": False,
                                      "error": "available memory < 3GB before start"})
            break
        prompts = [prompt] * n
        cfgs = [gen_cfg] * n
        print(f"concurrency {n} ...", flush=True)
        with MemSampler() as mem:
            t0 = time.perf_counter()
            try:
                results = pipe.generate(prompts, cfgs)
                total_s = time.perf_counter() - t0
                ok = True
                err = None
            except Exception as e:  # noqa: BLE001
                total_s = time.perf_counter() - t0
                results = []
                ok = False
                err = str(e)[:800]
        row = {
            "concurrency": n, "ok": ok, "error": err,
            "total_s": round(total_s, 2),
            "avg_per_request_s": round(total_s / n, 2) if ok else None,
            # ignore_eos=True makes every request emit exactly max_new_tokens
            "generated_tokens": n * a.max_new_tokens if ok else 0,
            "throughput_tok_s": None,
            "peak_rss_gb": round(mem.peak_rss / 1024**3, 2),
            "min_available_gb": round(mem.min_avail / 1024**3, 2),
        }
        if ok:
            try:
                row["perf_metrics_tokens_per_result"] = [
                    int(r.perf_metrics.get_num_generated_tokens()) for r in results]
            except Exception:
                pass
        if ok and total_s > 0:
            row["throughput_tok_s"] = round(row["generated_tokens"] / total_s, 1)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        report["results"].append(row)
        if not ok:
            break
        if mem.min_avail < 3 * 1024**3:
            report["stopped_reason"] = "available memory dropped below 3GB"
            break

    del pipe
    gc.collect()

    print("loading LLMPipeline for sequential comparison ...", flush=True)
    t0 = time.perf_counter()
    seq_pipe = g.LLMPipeline(a.model, a.device, **props)
    seq_load = time.perf_counter() - t0
    seq_cfg = g.GenerationConfig()
    seq_cfg.max_new_tokens = a.max_new_tokens
    seq_cfg.do_sample = False
    seq_cfg.ignore_eos = True
    counts = 8 * a.max_new_tokens
    with MemSampler() as mem:
        t0 = time.perf_counter()
        try:
            for _ in range(8):
                hist = g.ChatHistory([{"role": "user", "content": BASE_SENTENCE * 60}])
                hist.set_extra_context({"enable_thinking": False})
                seq_pipe.generate(hist, seq_cfg)
            seq_ok = True
            seq_err = None
        except Exception as e:  # noqa: BLE001
            seq_ok = False
            seq_err = str(e)[:800]
        seq_s = time.perf_counter() - t0
    report["sequential"] = {
        "ok": seq_ok, "error": seq_err, "requests": 8,
        "load_s": round(seq_load, 1), "total_s": round(seq_s, 2),
        "avg_per_request_s": round(seq_s / 8, 2),
        "generated_tokens": counts,
        "throughput_tok_s": round(counts / seq_s, 1) if seq_s > 0 else None,
        "peak_rss_gb": round(mem.peak_rss / 1024**3, 2),
        "min_available_gb": round(mem.min_avail / 1024**3, 2),
    }
    print(json.dumps(report["sequential"], ensure_ascii=False), flush=True)

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", a.out, flush=True)


if __name__ == "__main__":
    main()
