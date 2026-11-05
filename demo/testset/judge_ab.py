"""A/B harness for the support judge prompt, on labelled pairs only.

Replays the first-pass judge (plus the §5.3 evidence check) on (claim,
reference) pairs whose answer is known, with the excerpt the pipeline
actually used, so prompt variants can be compared without rerunning the
whole corpus:

- should flag: injected misattributions (injections/<paper>.json) and
  support alarms the ground truth labels true_issue;
- should not flag: support alarms the ground truth labels false_alarm.

Flagged = verified unsupported, or off_topic. Debatable and cannot_judge
pairs are left out.

Usage:
    python demo/testset/judge_ab.py --runs reports reports_r1105 \
        --variants head current
Variants are defined in VARIANTS below; "head" is the prompt in git HEAD.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))

import evaluate_corpus as ev  # noqa: E402
from citecheck.schema import CitationMarker  # noqa: E402
from citecheck.support import judge as J  # noqa: E402
from citecheck.support.layer import _apply_verdict, focus_sentence  # noqa: E402

LABELS = HERE / "ground_truth" / "labels.jsonl"


def _head_prompt() -> str:
    src = subprocess.run(
        ["git", "show", "HEAD:backend/citecheck/support/judge.py"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    ns: dict = {}
    exec(compile(src.replace("from ..llm.client import chat_json", ""),
                 "head_judge", "exec"), ns)
    return ns["_PROMPT"]


def _pairs(run: str) -> list[dict]:
    """Labelled (claim, ref) pairs of one run, with everything the judge reads."""
    reports = HERE / run
    tag = "r1105" if run.endswith("r1105") else ("base" if run == "reports" else run)
    labels = [json.loads(l) for l in LABELS.open() if l.strip()]
    labels = [r for r in labels if r["alarm_label"].startswith("support:")
              and "归属" not in r["alarm_label"]
              and (r.get("source_run") or "base") == tag]
    out = []
    for paper in ev.PAPERS + ev.PAPERS_EN:
        p = reports / f"{paper}_injected.json"
        if not p.exists():
            continue
        rep = ev.load(p)
        raw = json.loads(p.read_text())
        claims = {c["id"]: c for c in raw["claims"]}
        paras = {x["id"]: x["text"] for x in raw["paragraphs"]}
        marks: dict[str, list] = {}
        for m in raw["markers"]:
            marks.setdefault(m["paragraph_id"], []).append(CitationMarker(**m))
        refs = {x["id"]: x for x in raw["references"]}
        checks = {(s["claim_id"], s["ref_id"]): s for s in raw["support_checks"]}

        def add(cid, rid, want, why):
            s = checks.get((cid, rid))
            c = claims.get(cid)
            if not s or not c or not s.get("source_excerpt"):
                return
            out.append({
                "id": f"{run}/{paper}/{cid}/{rid}", "want": want, "why": why,
                "claim": c["text"], "excerpt": s["source_excerpt"],
                "title": s.get("source_title"), "entry": refs[rid]["raw"],
                "sentence": c.get("sentence"),
                "focused": focus_sentence(paras[c["paragraph_id"]], c.get("sentence"),
                                          c["start"], marks.get(c["paragraph_id"], []), rid),
                "cocited": [refs[o]["raw"] for o in
                            {r for m in c["marker_ids"] for mk in marks.get(c["paragraph_id"], [])
                             if mk.id == m for r in mk.ref_ids} if o != rid and o in refs],
            })

        for r in labels:
            if r["paper"] != paper or r["unit"][0] != "claim":
                continue
            if r["verdict"] not in ("true_issue", "false_alarm"):
                continue
            for rid in r["ref_ids"]:
                add(r["unit"][1], rid, r["verdict"] == "true_issue", r["verdict"])
        spec = json.loads((HERE / "injections" / f"{paper}.json").read_text())
        for inj in spec["injections"]:
            if inj["kind"] != "misattribution":
                continue
            para = ev.find_para(rep, inj["snippet"])
            ref = (ev.ref_id_by_key(rep, inj["cited_key"]) if "cited_key" in inj
                   else ev.ref_id_by_label(rep, inj["cited_label"]))
            _ok, _d, loc = ev.detect_injection(rep, inj)
            if para is None or ref is None:
                continue
            for cid, c in claims.items():
                if c["paragraph_id"] == para.id and (cid, ref) in checks:
                    if loc is None or ev.overlap((c["start"], c["end"]), (loc[1], loc[2])):
                        add(cid, ref, True, "injected")
    seen, uniq = set(), []
    for x in out:
        k = (x["id"], x["want"])
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq


VARIANTS = {}


def variant(name):
    def deco(fn):
        VARIANTS[name] = fn
        return fn
    return deco


@variant("head")
def _v_head(x):
    """git HEAD prompt, plain sentence (the baseline judge)."""
    return dict(prompt=_head_prompt(), sentence=x["sentence"])


@variant("current")
def _v_current(x):
    """working-tree prompt, focused sentence."""
    return dict(prompt=J._PROMPT, sentence=x["focused"])


async def _judge(x, cfg, sem):
    async with sem:
        out = await J.judge_claim(
            x["claim"], x["title"], x["excerpt"], sentence=cfg["sentence"],
            entry=x["entry"], cocited=x["cocited"], template=cfg["prompt"])
    if out is None:
        return None
    label, *_ = _apply_verdict(out, x["excerpt"])
    return label == "unsupported" or (out.off_topic and label in ("unsupported", "undetermined"))


async def main_async(a):
    pairs = [p for run in a.runs for p in _pairs(run)]
    pos = [p for p in pairs if p["want"]]
    neg = [p for p in pairs if not p["want"]]
    print(f"pairs: should flag {len(pos)} "
          f"(injected {sum(p['why'] == 'injected' for p in pos)}), "
          f"should not flag {len(neg)}")
    sem = asyncio.Semaphore(8)
    res = {}
    for name in a.variants:
        mk = VARIANTS[name]
        flags = await asyncio.gather(*[_judge(p, mk(p), sem) for p in pairs])
        c = Counter()
        for p, f in zip(pairs, flags):
            c[(p["why"], f)] += 1
        tp_inj = c[("injected", True)]
        tp_ti = c[("true_issue", True)]
        fp = c[("false_alarm", True)]
        fail = sum(v for (w, f), v in c.items() if f is None)
        res[name] = {"injected": [tp_inj, sum(v for (w, _), v in c.items() if w == "injected")],
                     "true_issue": [tp_ti, sum(v for (w, _), v in c.items() if w == "true_issue")],
                     "false_alarm": [fp, sum(v for (w, _), v in c.items() if w == "false_alarm")],
                     "failed": fail,
                     "flags": {p["id"] + "|" + p["why"]: f for p, f in zip(pairs, flags)}}
        r = res[name]
        print(f"{name:10s} injected {r['injected'][0]}/{r['injected'][1]}  "
              f"true_issue {r['true_issue'][0]}/{r['true_issue'][1]}  "
              f"false_alarm {r['false_alarm'][0]}/{r['false_alarm'][1]}  failed {fail}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=["reports", "reports_r1105"])
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS))
    ap.add_argument("--json")
    asyncio.run(main_async(ap.parse_args()))
    return 0



# ---- variants isolating the two prompt changes, and a scope-first judge
def _label_first(p: str) -> str:
    a = p.index("输出 JSON：")
    b = p.index("按顺序判断：")
    return (p[:a] + '输出 JSON：{{"label": "supported|partial|unsupported|undetermined", '
            '"evidence": "...", "rationale": "...", "off_topic": false}}。\n' + p[b:])


@variant("focus_lfirst")
def _v_focus_lfirst(x):
    """focused sentence, label first (isolates the reasoning-first order)."""
    return dict(prompt=_label_first(J._PROMPT), sentence=x["focused"])


@variant("plain_rfirst")
def _v_plain_rfirst(x):
    """plain sentence, reasoning first (isolates the citation tags)."""
    return dict(prompt=J._PROMPT, sentence=x["sentence"])


SCOPE = (
    '输出 JSON：{{"scope": "...", "rationale": "...", "evidence": "...", '
    '"label": "supported|partial|unsupported|undetermined", "off_topic": false}}。\n'
    "先在 scope 里用一句话写出句中由这篇文献负责的内容：如果引用只是指明某个"
    "方法、模型、数据集、工具或术语的出处，scope 就是这个名称；如果引用支撑一个"
    "结论或数值，scope 就是这个结论或数值。论断中不属于 scope 的部分（作者本人的"
    "做法、评价、数字，以及别的文献负责的内容）不参与判断。再写 rationale 和 "
    "evidence，最后给 label，label 必须与 rationale 一致。\n"
    "unsupported 只用于两种情况：被引文献是另一项工作，与 scope 说的不是一回事；"
    "原文明确写出了与 scope 相反或不同的内容。原文片段没有写到 scope 的内容时用 "
    "undetermined，不能用 unsupported。scope 只是一个名称、而文献正是提出或提供它的"
    "工作时用 supported。\n"
)


def _scope_prompt(p: str) -> str:
    a = p.index("输出 JSON：")
    b = p.index("按顺序判断：")
    return p[:a] + SCOPE + p[b:]


@variant("scope")
def _v_scope(x):
    """scope first, unsupported only on a different work or a contradiction."""
    return dict(prompt=_scope_prompt(J._PROMPT), sentence=x["focused"])


if __name__ == "__main__":
    raise SystemExit(main())
