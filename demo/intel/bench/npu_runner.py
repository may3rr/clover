"""Load (and optionally generate) one model on one device, write a JSON row.

Run as a child of npu_load_test.py so a cold NPU compilation can be killed
after a wall-clock budget.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

BASE = ("Academic citation verification requires checking whether each cited reference "
        "actually supports the claim it is attached to, whether the reported numbers and "
        "datasets match the source, and whether the cited work is about the same task. ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--device", default="NPU")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--max-prompt-len", type=int, default=2048)
    ap.add_argument("--min-response-len", type=int, default=256)
    ap.add_argument("--mode", choices=["load", "gen"], default="load")
    ap.add_argument("--max-new-tokens", type=int, default=128)
    ap.add_argument("--infer-timeout-s", type=float, default=600)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    import openvino_genai as g

    props = {"CACHE_DIR": a.cache}
    if a.device.upper() == "NPU":
        props["MAX_PROMPT_LEN"] = a.max_prompt_len
        props["MIN_RESPONSE_LEN"] = a.min_response_len

    t0 = time.perf_counter()
    pipe = g.LLMPipeline(a.model, a.device, **props)
    load_s = time.perf_counter() - t0
    row = {"device": a.device, "load_s": round(load_s, 2), "max_prompt_len": a.max_prompt_len,
           "min_response_len": a.min_response_len, "ok": True}

    if a.mode == "gen":
        tok = pipe.get_tokenizer()
        text = BASE * 60
        for _ in range(30):
            prompt = tok.apply_chat_template([{"role": "user", "content": text}], True,
                                             extra_context={"enable_thinking": False})
            ntok = int(tok.encode(prompt).input_ids.shape[-1])
            if 1250 <= ntok <= 1340:
                break
            if ntok > 1340:
                text = text[: int(len(text) * 0.92)]
            else:
                text += BASE
        cfg = g.GenerationConfig()
        cfg.max_new_tokens = a.max_new_tokens
        cfg.do_sample = False
        cfg.ignore_eos = True

        first = {"t": None}

        def streamer(chunk: str) -> bool:
            if first["t"] is None:
                first["t"] = time.perf_counter()
            return False

        hist = g.ChatHistory([{"role": "user", "content": text}])
        hist.set_extra_context({"enable_thinking": False})
        t1 = time.perf_counter()
        res = pipe.generate(hist, cfg, streamer)
        t2 = time.perf_counter()
        used = {}
        try:
            pm = res.perf_metrics
            used = {"prompt": int(pm.get_num_input_tokens()),
                    "completion": int(pm.get_num_generated_tokens())}
        except Exception:
            pass
        ttft = (first["t"] - t1) if first["t"] else None
        gen_tokens = used.get("completion") or a.max_new_tokens
        row.update({
            "prompt_tokens": ntok,
            "ttft_s": round(ttft, 3) if ttft else None,
            "total_s": round(t2 - t1, 2),
            "generated_tokens": gen_tokens,
            "decode_tok_s": round(gen_tokens / (t2 - first["t"]), 2) if first["t"] else None,
            "output_head": (res.texts[0] if hasattr(res, "texts") else str(res))[:300],
        })

    Path(a.out).write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
