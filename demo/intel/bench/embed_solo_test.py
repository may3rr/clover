import sys, time
from pathlib import Path
sys.path.insert(0, r"C:\clover\backend")
from citecheck.llm import ov

WINDOWS = [
    "We present a residual learning framework to ease the training of networks that are substantially deeper than those used previously.",
    "Training Deep Neural Networks is complicated by the fact that the distribution of each layer's inputs changes during training.",
    "We propose a method to jointly train on object detection and classification.",
    "批归一化将每一层的输入规范化为零均值单位方差，使得网络可以使用更高的学习率，训练收敛更快。",
    "The PASCAL Visual Object Classes challenge is a benchmark in visual object category recognition and detection.",
    "Product quantization decomposes the space into a Cartesian product of low dimensional subspaces and quantizes each subspace separately.",
] * 4

t0 = time.perf_counter()
emb = ov.Embedder(r"C:\clover-models\Qwen3-Embedding-0.6B-int8-ov", "NPU", 512,
                  r"C:\clover-models\.ov_cache_npu\len2048")
print("load", round(time.perf_counter() - t0, 2), "s device", emb.device, flush=True)
for i in range(10):
    t = time.perf_counter()
    emb.embed(WINDOWS)
    print(i, round(time.perf_counter() - t, 3), "s", flush=True)
