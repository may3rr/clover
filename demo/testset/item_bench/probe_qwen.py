"""Qwen probe: five support-judgment questions with hand-set answers, each
asked of several Qwen models with thinking off and on.

Questions come from the Chinese test papers with linked local PDFs; the
excerpt is built exactly as the pipeline builds it (local_source). The
prompt is the production judge prompt. Records label, off_topic, whether
the evidence is found verbatim (§5.3), latency, tokens and cost.

Usage:  python demo/testset/item_bench/probe_qwen.py [--set easy|hard] [--models a,b] [--repeats 2]
Writes runs/probe_qwen_<set>.jsonl and prints a table.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from openai import AsyncOpenAI  # noqa: E402

from citecheck.cache import Cache  # noqa: E402
from citecheck.config import get_settings  # noqa: E402
from citecheck.library.scan import scan_folder  # noqa: E402
from citecheck.library.source import local_source  # noqa: E402
from citecheck.support.evidence import locate_evidence  # noqa: E402
from citecheck.support.judge import JudgeOut, _PROMPT  # noqa: E402

BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
FLAG = {"unsupported", "partial"}

# (id, paper, claim id, ref id whose PDF is the source, claim override, gold)
# gold: "ok" = supported and no off_topic; "flag" = unsupported/partial or off_topic
QUESTIONS = [
    ("q1_supported", "liuqiao_kg", "c55", "r70", None, "ok"),
    ("q2_altered", "liuqiao_kg", "c55", "r70",
     "通过对描述逻辑的表现形式进行扩展,提出了一种基于组合描述逻辑的Tableau算法,"
     "基于实例的统计共现对不同领域的概念进行关联.", "flag"),
    ("q3_wrong_ref", "liuqiao_kg", "c3", ("yinhongpeng_odt", "r12"), None, "flag"),
    ("q4_cross_lingual", "yinhongpeng_odt", "c191", "r208", None, "ok"),
    ("q5_extra_clause", "liuqiao_kg", "c55", "r70",
     "通过对描述逻辑的表现形式进行扩展,提出了一种基于组合描述逻辑的Tableau算法,"
     "基于概念的相似性对不同领域的概念进行关联,并在WordNet上取得了95%的推理准确率.", "flag"),
]

# harder set: same-field wrong reference, a cross-lingual edit, a table
# header that should pass, a miscitation already in the manuscript, and a
# one-term edit of a Chinese claim
HARD = [
    ("h1_same_field_ref", "luohuilan_odt", "c26", "r10", None, "flag"),
    ("h2_cross_lingual_edit", "yinhongpeng_odt", "c191", "r208",
     "将跟踪问题看作是一个基于图的直推学习问题, 并以负样本和背景样本为顶点建立了一张图", "flag"),
    ("h3_table_header", "zhaoyangyang_tod", "c43", "r4", None, "ok"),
    ("h4_real_miscite", "luohuilan_odt", "c7", "r10", None, "flag"),
    ("h5_one_term_edit", "liuqiao_kg", "c20", "r17",
     "针对弱监督学习中标注数据不完全可靠的问题,基于Bootstrapping算法设计思想,提出了一种协同训练方法,"
     "通过向传统模型中引入依存句法特征进行协同训练,实现了对弱监督关系抽取模型的强化,"
     "在中文和英文数据集上关系抽取性能均得到了提升.", "flag"),
]


def _report(paper: str) -> dict:
    return json.loads((HERE.parent / "reports" / f"{paper}_clean.json").read_text("utf-8"))


def _pdf(paper: str, rid: str, cache: Cache):
    lib = _report(paper)["library"]
    doc = next(l["doc_id"] for l in lib["links"] if l["ref_id"] == rid)
    return next(p for p in scan_folder(ROOT / lib["folder"], cache) if p.doc.id == doc)


def build_questions(which: str = "easy") -> list[dict]:
    cache = Cache(get_settings().cache_path)
    out = []
    for qid, paper, cid, ref, override, gold in QUESTIONS if which == "easy" else HARD:
        claim = next(c for c in _report(paper)["claims"] if c["id"] == cid)
        text = override or claim["text"]
        sent = claim.get("sentence")
        if override and sent:
            sent = sent.replace(claim["text"], override) if claim["text"] in sent else override
        src_paper, rid = ref if isinstance(ref, tuple) else (paper, ref)
        pdf = _pdf(src_paper, rid, cache)
        src = local_source(pdf, text)
        out.append({"id": qid, "gold": gold, "claim": text, "sentence": sent,
                    "title": pdf.doc.title, "excerpt": src.excerpt})
    return out


async def ask(client, model: str, think: bool, q: dict) -> dict:
    prompt = _PROMPT.format(claim=q["claim"], sentence_line=f"所在句子：{q['sentence']}\n"
                            if q["sentence"] else "", title=q["title"], excerpt=q["excerpt"])
    t0 = time.time()
    try:
        r = await client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}], temperature=0,
            response_format={"type": "json_object"}, extra_body={"enable_thinking": think})
    except Exception as e:
        code = getattr(e, "code", None) or type(e).__name__
        return {"q": q["id"], "model": model, "think": think, "error": str(code)}
    dt = time.time() - t0
    msg = r.choices[0].message
    reasoning = (msg.model_extra or {}).get("reasoning_content") or ""
    u = r.usage
    rt = (u.completion_tokens_details.reasoning_tokens or 0) if u.completion_tokens_details else 0
    try:
        out = JudgeOut.model_validate_json(msg.content)
        found = out.evidence is None or locate_evidence(out.evidence, q["excerpt"]) is not None
        label, off = out.label, out.off_topic
    except Exception:
        out, found, label, off = None, False, "invalid", False
    pred = "flag" if label in FLAG or off else "ok"
    price = get_settings().llm.prices.get(model)
    cost = (u.prompt_tokens * price.input + u.completion_tokens * price.output) / 1e6 if price else None
    return {"q": q["id"], "model": model, "think": think, "label": label, "off_topic": off,
            "correct": pred == q["gold"], "evidence_found": found, "latency": round(dt, 1),
            "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
            "reasoning_tokens": rt, "reasoning_chars": len(reasoning), "cost_yuan": cost,
            "rationale": out.rationale if out else msg.content[:200], "reasoning": reasoning}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen3.8-flash,qwen3.8-27b,qwen3.8-max")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--set", default="easy", choices=["easy", "hard"])
    args = ap.parse_args()
    qs = build_questions(args.set)
    client = AsyncOpenAI(api_key=get_settings().dashscope_api_key, base_url=BASE, timeout=300)
    jobs = [ask(client, m, th, q) for m in args.models.split(",") for th in (False, True)
            for q in qs for _ in range(args.repeats)]
    rows = await asyncio.gather(*jobs)
    errs = {(r["model"], r["think"], r["error"]) for r in rows if "error" in r}
    for e in sorted(errs):
        print("error:", *e)
    rows = [r for r in rows if "error" not in r]
    out = HERE / "runs" / f"probe_qwen_{args.set}.jsonl"
    out.parent.mkdir(exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    print("| model | think | q | labels | correct | evidence ok | latency s | out tok | reasoning tok |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for m in args.models.split(","):
        for th in (False, True):
            for q in qs:
                rs = [r for r in rows if r["model"] == m and r["think"] == th and r["q"] == q["id"]]
                if not rs:
                    continue
                labs = ",".join(r["label"] + ("+off" if r["off_topic"] else "") for r in rs)
                print(f"| {m} | {th} | {q['id']} | {labs} | {sum(r['correct'] for r in rs)}/{len(rs)} | "
                      f"{sum(r['evidence_found'] for r in rs)}/{len(rs)} | "
                      f"{sum(r['latency'] for r in rs) / len(rs):.1f} | "
                      f"{sum(r['completion_tokens'] for r in rs) // len(rs)} | "
                      f"{sum(r['reasoning_tokens'] for r in rs) // len(rs)} |")
    cost = sum(r["cost_yuan"] or 0 for r in rows)
    print(f"total cost ≈ {cost:.3f} 元 ({len(rows)} calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
