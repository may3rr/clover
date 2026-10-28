"""SemanticCite-Checker-Qwen3-4B (local GGUF via llama-cpp) on the two
public sets, for comparison with our flash pipeline (external_eval.py).

    python checker_eval.py ci|sc [--limit N]

Prompt follows the model's Ollama Modelfile (Alpaca template, the
classification instructions as the system part) and SemanticCite's
analysis prompt; temperature 0. SemanticCite items use their own three
snippets and metadata; Citation-Integrity items use the article opening as
metadata and our first-pass excerpt (BM25 + embeddings + reranker) as the
snippets. Output goes to runs/external/checker_<kind>.jsonl.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

import external_eval as ee  # noqa: E402

MODEL = ee.EXT / "models" / "semanticcite-checker-qwen3-4b.Q4_K_M.gguf"

SYSTEM = """Analyze how well the following input citation claim is supported by the reference text snippets.

Classify the citation as one of:
SUPPORTED - Full alignment with source, complete representation
PARTIALLY_SUPPORTED - Core claim supported but missing critical information or oversimplified
UNSUPPORTED - Not found in source, contradicts reference, or misrepresentation
UNCERTAIN - Ambiguous claims, insufficient context, or unable to verify

You must respond with a valid JSON object:
{
    "classification": "SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED|UNCERTAIN",
    "reasoning": "Detailed explanation here",
    "confidence": 0.0
}

Only if Reference Document Information is available:
Use the Reference Document Information to understand the study context. When explaining your reasoning, mention if the citation claim fits the overall study described in the document information."""

TEMPLATE = ("Below is an instruction that describes a task, paired with an input that "
            "provides further context. Write a response that appropriately completes the "
            "request.\n\n### Instruction:\n{system}\n\n### Input:\n{prompt}\n\n### Response:\n")


def _prompt(claim: str, metadata: str, snippets: list[str]) -> str:
    chunks = [{"text": t, "location": {"chunk_id": i, "source": "reference_document"}}
              for i, t in enumerate(snippets)]
    return (f"Analyze how well the following citation is supported by the reference text "
            f"snippets.\nUse the Reference Document Information to understand the study "
            f"context.\n\nCitation: \"{claim}\"\nReference Document Information:\n{metadata}\n\n"
            f"Relevant Text Snippets:\n{json.dumps(chunks, indent=2, ensure_ascii=False)}")


async def _inputs(kind: str, limit: int | None):
    if kind == "sc":
        data = json.load(open(ee.EXT / "semanticcite" / "SemanticCite_dataset.json", encoding="utf-8"))
        want = {it["id"] for it in ee._sc_items(400)}
        out = []
        for i, d in enumerate(data):
            if f"sc{i}" not in want:
                continue
            out.append((f"sc{i}", d["output"]["classification"], d["input"]["claim"],
                        d["input"]["ref_metadata"].strip(),
                        [s["text"] for s in d["input"]["ref_snippets"]]))
        return out[:limit] if limit else out
    from citecheck.support.judge import search_terms
    from citecheck.support.sources import _bm25_excerpt

    out = []
    for it in ee._ci_items(limit):
        terms = await search_terms(it["claim"])
        query = " ".join([it["claim"], *terms])
        excerpt = await asyncio.to_thread(_bm25_excerpt, it["body"], query, 2500, 600)
        head, _, passages = excerpt.partition("\n\n")
        out.append((it["id"], it["gold"], it["claim"], head[:1200], [passages or head]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=("ci", "sc"))
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    from llama_cpp import Llama

    items = asyncio.run(_inputs(args.kind, args.limit))
    llm = Llama(model_path=str(MODEL), n_ctx=6144, n_gpu_layers=-1, verbose=False, seed=0)
    path = ee.EXT / f"checker_{args.kind}.jsonl"
    done = {}
    if path.exists():
        done = {json.loads(ln)["id"]: ln for ln in path.read_text("utf-8").split("\n") if ln.strip()}
    with open(path, "a", encoding="utf-8") as f:
        for n, (iid, gold, claim, meta, snippets) in enumerate(items):
            if iid in done:
                continue
            text = TEMPLATE.format(system=SYSTEM, prompt=_prompt(claim, meta, snippets))
            r = llm(text, max_tokens=400, temperature=0.0,
                    stop=["<|im_end|>", "### Input:", "### Response:"])
            raw = r["choices"][0]["text"]
            m = re.search(r"\"classification\"\s*:\s*\"([A-Z_]+)", raw)
            label = m.group(1) if m else "UNPARSED"
            f.write(json.dumps({"id": iid, "gold": gold, "label": label, "raw": raw[:600]},
                               ensure_ascii=False) + "\n")
            f.flush()
            if n % 25 == 0:
                print(n, len(items), label, flush=True)
    score(args.kind)
    return 0


def score(kind: str) -> None:
    rows = [json.loads(ln) for ln in (ee.EXT / f"checker_{kind}.jsonl").read_text("utf-8").split("\n") if ln.strip()]
    if kind == "ci":
        to = {"SUPPORTED": "ACCURATE", "PARTIALLY_SUPPORTED": "NOT_ACCURATE",
              "UNSUPPORTED": "NOT_ACCURATE"}
        pred = lambda r: to.get(r["label"], "NEI")  # noqa: E731
        labels = ["ACCURATE", "NOT_ACCURATE", "NEI"]
        problem = lambda r: r["gold"] != "ACCURATE"  # noqa: E731
    else:
        pred = lambda r: r["label"] if r["label"] != "UNPARSED" else "UNCERTAIN"  # noqa: E731
        labels = ["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "UNCERTAIN"]
        problem = lambda r: r["gold"] in ("PARTIALLY_SUPPORTED", "UNSUPPORTED")  # noqa: E731
    n = len(rows)
    acc = sum(pred(r) == r["gold"] for r in rows) / n
    f1 = ee._f1(rows, labels, pred)
    macro = sum(v[0] for v in f1.values()) / len(labels)
    print(f"checker {kind}: {n} 条，标准准确率 {acc:.3f}，macro-F1 {macro:.3f}")
    for lab, (f, p, r_, g) in f1.items():
        print(f"| {lab} | {g} | {f:.2f} | {p:.2f} | {r_:.2f} |")
    for name, flag in (("partial 与 unsupported 都算报警",
                        lambda r: r["label"] in ("PARTIALLY_SUPPORTED", "UNSUPPORTED")),
                       ("只有 unsupported 算报警", lambda r: r["label"] == "UNSUPPORTED")):
        tp = sum(1 for r in rows if flag(r) and problem(r))
        fp = sum(1 for r in rows if flag(r) and not problem(r))
        fn = sum(1 for r in rows if not flag(r) and problem(r))
        print(f"{name}：报警 {tp + fp} 条，报警准确率 {tp / max(tp + fp, 1):.2f}，查出 {tp}/{tp + fn} = {tp / max(tp + fn, 1):.2f}")
    print("预测分布", Counter(r["label"] for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
