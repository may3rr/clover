"""Real-prompt quality check for the local LLM: judge and extract.

6 judge samples (3 zh / 3 en: 2 supported, 2 numeric mismatch, 2 off-topic)
and 6 extract samples (3 zh / 3 en). Validates JSON and the Pydantic schema
used by the product, records latency and raw output, and checks that no
<think> block is emitted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLOVER = HERE.parents[2]
sys.path.insert(0, str(CLOVER / "backend"))

from citecheck.llm.local import _extract_json  # noqa: E402
from citecheck.support.claims import _ClaimsOut, _PROMPT as EXTRACT_PROMPT  # noqa: E402
from citecheck.support.judge import JudgeOut, _PROMPT as JUDGE_PROMPT  # noqa: E402

JUDGE_SAMPLES = [
    {
        "id": "en_supported", "lang": "en", "expected": "supported",
        "claim": "We adopt Faster R-CNN, which runs at 5 frames per second on a GPU, as our detection baseline.",
        "title": "Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks",
        "excerpt": ("We propose a Region Proposal Network (RPN) that shares full-image convolutional "
                    "features with the detection network, thus enabling nearly cost-free region proposals. "
                    "Our detection system runs at 5 frames per second on a GPU for the VGG-16 model."),
    },
    {
        "id": "zh_supported", "lang": "zh", "expected": "supported",
        "claim": "批归一化通过减少内部协变量偏移来加速深度网络训练",
        "title": "Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift",
        "excerpt": ("Training Deep Neural Networks is complicated by the fact that the distribution of "
                    "each layer's inputs changes during training. We refer to this phenomenon as internal "
                    "covariate shift, and address the problem by normalizing layer inputs."),
    },
    {
        "id": "en_numeric_mismatch", "lang": "en", "expected": "unsupported",
        "claim": "YOLO9000 runs at 50 frames per second on a GPU.",
        "title": "YOLO9000: Better, Faster, Stronger",
        "excerpt": ("YOLO9000 is trained jointly on ImageNet classification and COCO detection data. "
                    "Our model runs at 5 frames per second on a GPU while achieving competitive accuracy."),
    },
    {
        "id": "zh_numeric_mismatch", "lang": "zh", "expected": "unsupported",
        "claim": "该方法在 ImageNet 上达到 90% 的准确率。",
        "title": "Deep Residual Learning for Image Recognition",
        "excerpt": "我们在 ImageNet 验证集上的单模型准确率为 60.1%，集成模型为 63.4%。",
    },
    {
        "id": "en_off_topic", "lang": "en", "expected": "unsupported", "expect_off_topic": True,
        "claim": "Huang et al. proposed FusionNet for infrared and visible image fusion.",
        "title": "Deep Residual Learning for Image Recognition",
        "excerpt": ("We present a residual learning framework to ease the training of networks that are "
                    "substantially deeper than those used previously. We explicitly reformulate the layers "
                    "as learning residual functions with reference to the layer inputs."),
    },
    {
        "id": "zh_off_topic", "lang": "zh", "expected": "unsupported", "expect_off_topic": True,
        "claim": "Zhang 等人提出的 FusionNet 用于多模态医学图像融合。",
        "title": "Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift",
        "excerpt": "批归一化将每一层的输入规范化为零均值单位方差，使得网络可以使用更高的学习率，训练收敛更快。",
    },
]

EXTRACT_SAMPLES = [
    {"id": "en_1", "lang": "en", "sentence": "We adopt Faster R-CNN ⟦m1⟧, which runs at 5 frames per second on a GPU, as our detection baseline."},
    {"id": "en_2", "lang": "en", "sentence": "Residual connections ⟦m1⟧ ease the training of very deep networks, and batch normalization ⟦m2⟧ speeds up convergence."},
    {"id": "en_3", "lang": "en", "sentence": "The model is trained on COCO ⟦m1⟧ and achieves 5 FPS on a single GPU ⟦m2⟧."},
    {"id": "zh_1", "lang": "zh", "sentence": "我们采用 Faster R-CNN ⟦m1⟧ 作为检测基线，它在 GPU 上达到每秒 5 帧。"},
    {"id": "zh_2", "lang": "zh", "sentence": "批归一化 ⟦m1⟧ 和残差连接 ⟦m2⟧ 使得训练上百层的网络成为可能。"},
    {"id": "zh_3", "lang": "zh", "sentence": "该数据集包含 12 万张图像 ⟦m1⟧，覆盖 80 个类别 ⟦m2⟧。"},
]


def judge_prompt(s: dict) -> str:
    return JUDGE_PROMPT.format(
        claim=s["claim"], sentence_line="", entry_line="", cocited_line="",
        title=s["title"], excerpt=s["excerpt"])


def extract_prompt(s: dict) -> str:
    return EXTRACT_PROMPT.format(sentence=s["sentence"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=r"C:\clover-models\Qwen3-8B-int4-ov")
    ap.add_argument("--device", default="GPU")
    ap.add_argument("--cache", default=r"C:\clover-models\.openvino_cache")
    ap.add_argument("--out", default=r"C:\clover\demo\intel\bench\quality-8b-gpu.json")
    ap.add_argument("--max-new-tokens", type=int, default=256)
    a = ap.parse_args()

    from citecheck.llm import ov

    t0 = time.perf_counter()
    gen = ov.Generator(a.model, a.device, 2048, 256, a.cache)
    load_s = time.perf_counter() - t0
    print(f"loaded {a.model} on {gen.device} in {load_s:.1f}s", flush=True)

    report: dict = {
        "model": a.model, "requested_device": a.device, "device": gen.device,
        "load_s": round(load_s, 1), "judge": [], "extract": [],
    }

    for s in JUDGE_SAMPLES:
        prompt = judge_prompt(s)
        t0 = time.perf_counter()
        text, usage = gen.generate([{"role": "user", "content": prompt}], a.max_new_tokens)
        dt = time.perf_counter() - t0
        raw = text
        js = _extract_json(raw)
        obj = None
        schema_ok = False
        parse_err = None
        try:
            obj = json.loads(js) if js else None
            if obj is not None:
                JudgeOut.model_validate(obj)
                schema_ok = True
        except Exception as e:  # noqa: BLE001
            parse_err = str(e)[:400]
        label = obj.get("label") if isinstance(obj, dict) else None
        off_topic = bool(obj.get("off_topic")) if isinstance(obj, dict) else None
        correct = (label == s["expected"]) and (
            not s.get("expect_off_topic") or off_topic is True)
        row = {
            "id": s["id"], "lang": s["lang"], "expected": s["expected"],
            "expect_off_topic": bool(s.get("expect_off_topic")),
            "s": round(dt, 2), "usage": usage, "json_ok": js is not None,
            "schema_ok": schema_ok, "parse_error": parse_err,
            "label": label, "off_topic": off_topic, "correct": correct,
            "has_think": "<think>" in raw or "</think>" in raw,
            "raw": raw[:1200],
        }
        print(json.dumps({k: row[k] for k in ("id", "s", "json_ok", "schema_ok", "label", "correct", "has_think")}, ensure_ascii=False), flush=True)
        report["judge"].append(row)

    for s in EXTRACT_SAMPLES:
        prompt = extract_prompt(s)
        t0 = time.perf_counter()
        text, usage = gen.generate([{"role": "user", "content": prompt}], a.max_new_tokens)
        dt = time.perf_counter() - t0
        raw = text
        js = _extract_json(raw)
        obj = None
        schema_ok = False
        parse_err = None
        checks = {}
        try:
            obj = json.loads(js) if js else None
            if obj is not None:
                _ClaimsOut.model_validate(obj)
                schema_ok = True
        except Exception as e:  # noqa: BLE001
            parse_err = str(e)[:400]
        sentence_wo_markers = re.sub(r"⟦m\d+⟧", "", s["sentence"])
        claims = obj.get("claims", []) if isinstance(obj, dict) else []
        markers = set(re.findall(r"⟦(m\d+)⟧", s["sentence"]))
        checks = {
            "claim_count": len(claims),
            "texts_in_sentence": all(isinstance(c.get("text"), str) and c["text"] in sentence_wo_markers for c in claims if isinstance(c, dict)),
            "markers_valid": all(set(c.get("marker_ids", [])) <= markers and set(c.get("marker_ids", [])) for c in claims if isinstance(c, dict)),
        }
        row = {
            "id": s["id"], "lang": s["lang"], "s": round(dt, 2), "usage": usage,
            "json_ok": js is not None, "schema_ok": schema_ok, "parse_error": parse_err,
            "has_think": "<think>" in raw or "</think>" in raw,
            **checks, "raw": raw[:1200],
        }
        print(json.dumps({k: row[k] for k in ("id", "s", "json_ok", "schema_ok", "claim_count", "texts_in_sentence", "markers_valid", "has_think")}, ensure_ascii=False), flush=True)
        report["extract"].append(row)

    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", a.out, flush=True)


if __name__ == "__main__":
    main()
