"""Intel 机器可行性验证（一次性脚本，不并入产品）。

在组委会或测试用的 Intel 电脑上逐个设备加载三个本地模型，记下能否编译、
首次与缓存后的加载耗时、单次推理耗时，以及各设备结果与 CPU 的一致程度。

    cd backend
    python ../demo/intel/probe.py --models D:/clover-models --out ../demo/intel/probe-<机器名>.json

--models 目录下放从 hf-mirror 下载的三个 IR 目录（名字可用 --embed 等单独指定）：
    Qwen3-Embedding-0.6B-int8-ov  Qwen3-Reranker-0.6B-int8-ov  Qwen3-1.7B-int4-ov
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

# 取自真实稿件的引用句与被引原文片段，规模与产品里的检索窗口一致
QUERIES = [
    "Residual learning eases the training of networks that are substantially deeper than those used previously",
    "批归一化通过减少内部协变量偏移来加速深度网络训练",
    "YOLO9000 is trained jointly on ImageNet classification and COCO detection data",
]
WINDOWS = [
    "We present a residual learning framework to ease the training of networks that are substantially deeper than those used previously. We explicitly reformulate the layers as learning residual functions with reference to the layer inputs.",
    "Training Deep Neural Networks is complicated by the fact that the distribution of each layer's inputs changes during training. We refer to this phenomenon as internal covariate shift, and address the problem by normalizing layer inputs.",
    "We propose a method to jointly train on object detection and classification. Using this method we train YOLO9000 simultaneously on the COCO detection dataset and the ImageNet classification dataset.",
    "批归一化将每一层的输入规范化为零均值单位方差，使得网络可以使用更高的学习率，训练收敛更快。",
    "The PASCAL Visual Object Classes challenge is a benchmark in visual object category recognition and detection, providing the vision community with a standard dataset of images and annotation.",
    "Product quantization decomposes the space into a Cartesian product of low dimensional subspaces and quantizes each subspace separately.",
] * 4  # 24 个窗口，接近一篇被引文献一次检索的批量

EXTRACT_SENTENCES = [
    "We adopt Faster R-CNN ⟦m1⟧, which runs at 5 frames per second on a GPU, as our detection baseline.",
    "批归一化 ⟦m1⟧ 和残差连接 ⟦m2⟧ 使得训练上百层的网络成为可能。",
]


def _devices() -> list[str]:
    from citecheck.llm import ov

    present = ov.available_devices()
    return [d for d in ov.device_order("NPU,GPU,CPU", present)]


def _device_names() -> dict[str, str]:
    import openvino as ov

    core = ov.Core()
    out = {}
    for d in core.available_devices:
        try:
            out[d] = str(core.get_property(d, "FULL_DEVICE_NAME"))
        except Exception as e:  # noqa: BLE001
            out[d] = f"? ({e})"
    return out


def _timed(fn):
    t = time.perf_counter()
    v = fn()
    return v, time.perf_counter() - t


def probe_embed(path: str, dev: str, cache: str, ref=None) -> dict:
    import numpy as np

    from citecheck.llm import ov
    from citecheck.llm.embed import _INSTRUCT

    r: dict = {"device": dev}
    emb, r["load_cold_s"] = _timed(lambda: ov.Embedder(path, dev, 512, cache))
    _, r["load_warm_s"] = _timed(lambda: ov.Embedder(path, dev, 512, cache))
    docs, r["embed_24_windows_s"] = _timed(lambda: emb.embed(WINDOWS))
    qs, r["embed_3_queries_s"] = _timed(lambda: emb.embed([_INSTRUCT + q for q in QUERIES]))
    sims = qs @ docs[:6].T
    r["top1"] = [int(i) for i in sims.argmax(axis=1)]
    r["top1_expected"] = [0, 3, 2]
    if ref is not None:
        r["cos_vs_cpu_min"] = float(np.min(np.sum(docs * ref, axis=1)))
    r["_vecs"] = docs
    return r


def probe_rerank(path: str, dev: str, cache: str) -> dict:
    from citecheck.llm import ov

    r: dict = {"device": dev}
    rr, r["load_cold_s"] = _timed(lambda: ov.Reranker(path, dev, 512, cache))
    r["qwen3_template"] = rr.qwen3
    scores, r["rerank_6_s"] = _timed(lambda: rr.rerank(QUERIES[0], WINDOWS[:6]))
    r["scores"] = [round(s, 4) for s in scores]
    _, r["rerank_24_s"] = _timed(lambda: rr.rerank(QUERIES[2], WINDOWS))
    return r


def probe_llm(path: str, dev: str, cache: str) -> dict:
    from citecheck.llm import local, ov
    from citecheck.support.claims import _PROMPT

    r: dict = {"device": dev}
    gen, r["load_cold_s"] = _timed(lambda: ov.Generator(path, dev, 1024, 256, cache))
    outs = []
    for s in EXTRACT_SENTENCES:
        msgs = [{"role": "user", "content": _PROMPT.format(sentence=s)}]
        (text, usage), dt = _timed(lambda: gen.generate(msgs, 256))
        js = local._extract_json(text)
        outs.append({"s": dt, "usage": usage, "json_ok": js is not None,
                     "out": (js or text)[:400]})
    r["extract"] = outs
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=str(Path.home() / "models" / "openvino"))
    ap.add_argument("--embed", default="Qwen3-Embedding-0.6B-int8-ov")
    ap.add_argument("--rerank", default="Qwen3-Reranker-0.6B-int8-ov")
    ap.add_argument("--llm", default="Qwen3-1.7B-int4-ov")
    ap.add_argument("--only", choices=["embed", "rerank", "llm"], action="append")
    ap.add_argument("--out", default="probe.json")
    a = ap.parse_args()

    import openvino as ov_rt
    import openvino_genai

    root = Path(a.models).expanduser()
    report: dict = {
        "machine": platform.platform(), "processor": platform.processor(),
        "python": sys.version.split()[0], "openvino": ov_rt.__version__,
        "openvino_genai": openvino_genai.__version__,
        "devices": _device_names(), "results": {},
    }
    print(json.dumps({k: report[k] for k in ("machine", "openvino", "devices")},
                     ensure_ascii=False, indent=1))
    devs = _devices()
    todo = a.only or ["embed", "rerank", "llm"]
    for kind in todo:
        path = str(root / getattr(a, kind))
        if not Path(path).is_dir():
            print(f"[{kind}] 跳过：没有 {path}")
            continue
        rows, ref = [], None
        for dev in reversed(devs):  # CPU 先跑，作为其他设备的参照
            cache = tempfile.mkdtemp(prefix=f"ovcache-{kind}-{dev}-")
            print(f"[{kind}] {dev} …", flush=True)
            try:
                if kind == "embed":
                    row = probe_embed(path, dev, cache, ref)
                    if dev == "CPU":
                        ref = row["_vecs"]
                    row.pop("_vecs")
                elif kind == "rerank":
                    row = probe_rerank(path, dev, cache)
                else:
                    row = probe_llm(path, dev, cache)
                row["ok"] = True
            except Exception as e:  # noqa: BLE001 — record and go on
                row = {"device": dev, "ok": False, "error": str(e)[:600]}
            finally:
                shutil.rmtree(cache, ignore_errors=True)
            print(json.dumps(row, ensure_ascii=False, indent=1), flush=True)
            rows.append(row)
        report["results"][kind] = rows
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写入 {a.out}")


if __name__ == "__main__":
    main()
