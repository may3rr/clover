import time, sys
import openvino_genai as g

model = r"C:\clover-models\Qwen3.5-9B-int4-ov"
cache = r"C:\clover-models\.ov_cache_vlm_qwen35_9b"
t0 = time.perf_counter()
try:
    pipe = g.VLMPipeline(model, "GPU", CACHE_DIR=cache)
    print("loaded VLM in", round(time.perf_counter() - t0, 1), "s", flush=True)
    cfg = g.GenerationConfig()
    cfg.max_new_tokens = 32
    cfg.do_sample = False
    t1 = time.perf_counter()
    res = pipe.generate("用一句话解释什么是引用核查。", [], cfg)
    print("gen", round(time.perf_counter() - t1, 1), "s", flush=True)
    print(str(res)[:500])
except Exception as e:
    print("VLM ERROR:", str(e)[:1500])
