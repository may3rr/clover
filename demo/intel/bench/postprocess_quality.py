"""Recompute quality checks with the product's normalization.

The first pass compared claim text literally; the product allows whitespace /
full-width / CJK-spacing differences, so record both.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CLOVER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CLOVER / "backend"))

from citecheck.support.evidence import normalize_text  # noqa: E402

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))

samples = {
    "en_1": "We adopt Faster R-CNN ⟦m1⟧, which runs at 5 frames per second on a GPU, as our detection baseline.",
    "en_2": "Residual connections ⟦m1⟧ ease the training of very deep networks, and batch normalization ⟦m2⟧ speeds up convergence.",
    "en_3": "The model is trained on COCO ⟦m1⟧ and achieves 5 FPS on a single GPU ⟦m2⟧.",
    "zh_1": "我们采用 Faster R-CNN ⟦m1⟧ 作为检测基线，它在 GPU 上达到每秒 5 帧。",
    "zh_2": "批归一化 ⟦m1⟧ 和残差连接 ⟦m2⟧ 使得训练上百层的网络成为可能。",
    "zh_3": "该数据集包含 12 万张图像 ⟦m1⟧，覆盖 80 个类别 ⟦m2⟧。",
}

for row in data["extract"]:
    sent = re.sub(r"⟦m\d+⟧", "", samples[row["id"]])
    raw = row.get("raw", "")
    m = re.search(r"\{.*\}", raw, re.S)
    claims = []
    if m:
        try:
            claims = json.loads(m.group(0)).get("claims", [])
        except Exception:
            pass
    norm_sent = normalize_text(sent)
    row["texts_in_sentence_norm"] = all(
        isinstance(c.get("text"), str) and normalize_text(c["text"]) in norm_sent
        for c in claims) if claims else False
    row["exact_ok"] = row.get("texts_in_sentence", False)
    row["normalized_ok"] = row["texts_in_sentence_norm"]
    row["semantic_ok"] = bool(row.get("json_ok") and row.get("schema_ok") and row["normalized_ok"])
    row["marker_ids"] = [c.get("marker_ids") for c in claims]

for row in data["judge"]:
    row["label_correct"] = row.get("label") == row.get("expected")
    if row.get("expect_off_topic"):
        row["off_topic_correct"] = row.get("off_topic") is True
    else:
        row["off_topic_correct"] = True

data["summary"] = {
    "judge_label_correct": sum(1 for r in data["judge"] if r.get("label_correct")),
    "judge_total": len(data["judge"]),
    "off_topic_flag_correct": sum(1 for r in data["judge"] if r.get("off_topic_correct")),
    "off_topic_expected": sum(1 for r in data["judge"] if r.get("expect_off_topic")),
    "extract_json_schema_ok": sum(1 for r in data["extract"] if r.get("json_ok") and r.get("schema_ok")),
    "extract_total": len(data["extract"]),
    "extract_exact_substring_ok": sum(1 for r in data["extract"] if r.get("exact_ok")),
    "extract_normalized_ok": sum(1 for r in data["extract"] if r.get("normalized_ok")),
    "think_leaks": sum(1 for r in data["judge"] + data["extract"] if r.get("has_think")),
}
path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(data["summary"], ensure_ascii=False, indent=1))
