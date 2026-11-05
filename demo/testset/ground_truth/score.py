"""Score a Clover run against the hand-labelled ground truth of clean-manuscript alarms.

The ground truth (labels.jsonl) labels every pre-existing alarm unit of the
baseline run: one record per alarm, verdict true_issue / false_alarm /
debatable / cannot_judge. Units are the ones evaluate_corpus.py produces
(claim / reference / sentence span); a unit is matched across runs by
(paper, text key), the same text key evaluate_corpus.py uses to line clean
and injected runs up, and an alarm inside a unit by a stable alarm key
(layer label + reference ids, or old->new for a typo revision).

No model is called.

Usage:
    python demo/testset/ground_truth/score.py                       # baseline reports
    python demo/testset/ground_truth/score.py --reports DIR         # a new run
    python demo/testset/ground_truth/score.py --reports DIR --json out.json
    python demo/testset/ground_truth/score.py --add-keys            # (re)write alarm_key into labels.jsonl

Output: precision of the run's pre-existing alarms over the labelled ones,
per language (strict = true_issue / labelled, lenient = (true_issue +
debatable) / labelled), at unit level and at alarm level; alarms the run no
longer raises (false alarms removed, real issues lost); new alarms with no
label yet (to annotate).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTSET = HERE.parent
sys.path.insert(0, str(TESTSET))
sys.path.insert(0, str(TESTSET / "precision_audit"))

import evaluate_corpus as ev  # noqa: E402
from build_pool import unit_objects  # noqa: E402

LABELS = HERE / "labels.jsonl"
COMPANION = ("status:", "label:")  # internal labels that travel with a finding


def alarm_key(label: str, kind: str, o) -> str:
    """Stable identity of one alarm inside a unit across runs."""
    if kind == "finding":
        return f"{label}|{','.join(sorted(o.refs))}"
    if kind == "ref_check":
        return f"{label}|{o.ref_id}"
    if kind == "support_check":
        return f"{label}|{o.ref_id}"
    return f"{label}|{o.old}->{o.new}"  # typo revision


def _aid(kind, o):
    if kind in ("finding", "revision"):
        return str(o.id)
    if kind == "ref_check":
        return str(o.ref_id)
    return f"{o.claim_id}/{o.ref_id}"


def run_alarms(reports: Path):
    """paper -> (lang, {(text_key, alarm_key): (unit, label, kind, alarm_id)})
    for every pre-existing alarm of the run, exactly as evaluate_corpus
    counts them. Identical keys (two table captions with the same text, the
    same typo fixed twice in one sentence) get an occurrence suffix #n."""
    out = {}
    for lang, papers in (("zh", ev.PAPERS), ("en", ev.PAPERS_EN)):
        for paper in papers:
            inj, clean = reports / f"{paper}_injected.json", reports / f"{paper}_clean.json"
            if not inj.exists() or not clean.exists():
                continue
            spec = json.loads((TESTSET / "injections" / f"{paper}.json").read_text())
            rep = ev.load(inj)
            res = ev.score(rep, ev.load(clean), spec)
            U = ev.Units(rep)
            objs = unit_objects(U)
            alarms, seen = {}, Counter()
            for entry in res["pre_existing_units"]:
                unit = tuple(entry["unit"])
                tk = U.key(unit)
                for label, kind, o in objs[unit]:
                    ak = alarm_key(label, kind, o)
                    n = seen[(tk, ak)]
                    seen[(tk, ak)] += 1
                    alarms[(tk, ak + (f"#{n}" if n else ""))] = (unit, label, kind, _aid(kind, o))
            out[paper] = (lang, alarms, res["counts"])
    return out


def _base(ak: str) -> str:
    return ak.split("#")[0]


def _fuzzy(cands, tk: str, used: set[int], threshold: float = 0.6):
    """The unused label whose unit text overlaps ``tk`` most, if the
    overlap (longest common block over the shorter text) clears the bar."""
    from difflib import SequenceMatcher
    best, best_s = None, threshold
    a = tk[4:]
    for r in cands:
        if id(r) in used:
            continue
        b = r["text_key"][4:]
        if not a or not b:
            continue
        m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(
            0, len(a), 0, len(b))
        sc = m.size / min(len(a), len(b))
        if sc > best_s:
            best, best_s = r, sc
    if best is not None:
        used.add(id(best))
    return best


def load_labels():
    return [json.loads(l) for l in LABELS.open() if l.strip()]


def add_keys(reports: Path):
    """Attach alarm_key to every label, from the run the labels were made on."""
    labels = load_labels()
    keyed = {}
    for paper, (_, alarms, _c) in run_alarms(reports).items():
        for (tk, ak), (unit, label, kind, aid) in alarms.items():
            keyed[(paper, unit, label, aid)] = ak
    for r in labels:
        r["alarm_key"] = keyed[(r["paper"], tuple(r["unit"]), r["alarm_label"], str(r["alarm_id"]))]
    LABELS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in labels))
    print(f"alarm_key written for {len(labels)} labels")


def prec(c: Counter):
    n = sum(c.values())  # cannot_judge stays in the denominator
    if not n:
        return None, None, 0
    return c["true_issue"] / n, (c["true_issue"] + c["debatable"]) / n, n


def unit_verdict(vs):
    """A unit is a true positive if any of its alarms is a real issue."""
    for v in ("true_issue", "debatable", "false_alarm", "cannot_judge"):
        if v in vs:
            return v


def score(reports: Path):
    labels = load_labels()
    runs = run_alarms(reports)
    by_key = {(r["paper"], r["text_key"], r["alarm_key"]): r for r in labels}
    labels_by_alarm = defaultdict(list)
    for r in labels:
        labels_by_alarm[(r["paper"], _base(r["alarm_key"]))].append(r)
    used: set[int] = set()
    # exact matches claim their labels first, so a fuzzy match never
    # steals a label another unit matches exactly
    for paper, (_pl, alarms, _c) in runs.items():
        for (tk, ak) in alarms:
            r = by_key.get((paper, tk, ak))
            if r is not None:
                used.add(id(r))
    res = {"reports": str(reports), "langs": {}}
    for lang in ("zh", "en"):
        alarm_c, unit_v, gone, new = Counter(), defaultdict(list), Counter(), []
        cause = Counter()
        tp = fp_new = 0
        matched = []
        for paper, (pl, alarms, counts) in runs.items():
            if pl != lang:
                continue
            tp += counts["tp"]
            fp_new += counts["fp_new"]
            pending = []
            for (tk, ak), val in alarms.items():
                r = by_key.get((paper, tk, ak))
                if r is None:
                    pending.append((tk, ak, val))
                else:
                    matched.append((paper, tk, ak, val, r))
            # a changed claim extraction rewrites the unit text: fall back
            # to the same alarm (label + refs) on an overlapping text
            for tk, ak, val in pending:
                r = _fuzzy(labels_by_alarm.get((paper, _base(ak)), []), tk, used)
                if r is None:
                    unit = val[0]
                    new.append({"paper": paper, "unit": list(unit), "alarm": ak, "text": tk[4:84]})
                else:
                    matched.append((paper, tk, ak, val, r))
        for paper, tk, ak, (unit, label, kind, _), r in matched:
            used.add(id(r))
            if label.startswith(COMPANION):
                continue
            alarm_c[r["verdict"]] += 1
            unit_v[(paper, r["unit_id"])].append(r["verdict"])
            if r["verdict"] == "false_alarm":
                cause[r["cause"]] += 1
        for r in labels:
            if r["lang"] != lang or r["paper"] not in runs or r["alarm_label"].startswith(COMPANION):
                continue
            if id(r) not in used:
                gone[r["verdict"]] += 1
        unit_c = Counter(unit_verdict(v) for v in unit_v.values())
        s_a, l_a, n_a = prec(alarm_c)
        s_u, l_u, n_u = prec(unit_c)
        # whole-corpus precision as evaluate_corpus defines it, with the
        # hand labels replacing "every clean-run alarm is a false positive";
        # units carrying only unlabelled alarms count as false positives
        new_units = {(u["paper"], tuple(u["unit"])) for u in new} - set(unit_v)
        den = tp + fp_new + n_u + len(new_units)
        corpus = ((tp + unit_c["true_issue"]) / den if den else None,
                  (tp + unit_c["true_issue"] + unit_c["debatable"]) / den if den else None)
        res["langs"][lang] = {
            "alarms": dict(alarm_c), "alarm_strict": s_a, "alarm_lenient": l_a,
            "units": dict(unit_c), "unit_strict": s_u, "unit_lenient": l_u,
            "injected_tp": tp, "injected_fp_new": fp_new, "unlabelled_units": len(new_units),
            "corpus_strict": corpus[0], "corpus_lenient": corpus[1],
            "false_alarm_causes": dict(cause.most_common()),
            "no_longer_raised": dict(gone), "unlabelled_new": len(new), "unlabelled": new,
        }
    return res


def _f(x):
    return "-" if x is None else f"{x:.3f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reports", type=Path, default=TESTSET / "reports")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--add-keys", action="store_true")
    a = ap.parse_args()
    if a.add_keys:
        add_keys(a.reports.resolve())
        return 0
    res = score(a.reports.resolve())
    for lang, d in res["langs"].items():
        print(f"\n== {lang}")
        print(f"  units  {d['units']}  strict {_f(d['unit_strict'])}  lenient {_f(d['unit_lenient'])}")
        print(f"  alarms {d['alarms']}  strict {_f(d['alarm_strict'])}  lenient {_f(d['alarm_lenient'])}")
        print(f"  corpus (injected TP {d['injected_tp']}, new FP {d['injected_fp_new']}, "
              f"unlabelled units {d['unlabelled_units']}): strict {_f(d['corpus_strict'])}  "
              f"lenient {_f(d['corpus_lenient'])}")
        print(f"  false-alarm causes {d['false_alarm_causes']}")
        print(f"  labelled alarms no longer raised {d['no_longer_raised']}")
        print(f"  new alarms without a label: {d['unlabelled_new']}")
        for u in d["unlabelled"][:15]:
            print(f"    {u['paper']} {u['alarm']} | {u['text']}")
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
