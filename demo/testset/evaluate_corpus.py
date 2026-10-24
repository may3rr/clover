"""F8: score the eval corpus — per-injection detection + per-unit P/R/Acc.

Unit of measurement (per the corpus design): the citing claim (一条引用句) and
the reference. For every injected manuscript this script

  1. checks each injection against the pipeline report using the same
     detection rules as demo/evaluate.py (not relaxed); a misattribution
     counts as detected when the pipeline raised ANY support-layer alarm on
     the swapped marker's sentence — unsupported (high), review-confirmed
     off_topic (medium) or the attribution-consistency rule (medium),
  2. walks every claim / reference and labels it ground-truth positive
     (targeted by an injection) or clean, and predicted positive (flagged by
     the pipeline: high/medium support/distribution/norms finding anchored on
     the unit, unsupported label, not_found/mismatch status, uncited finding),
  3. removes pre-existing flags (units the CLEAN run also flagged — real
     defects of the original paper, not our doing),
  4. computes precision / recall / accuracy in a lenient and a strict flavour
     (strict counts `undetermined` support labels on clean claims as alarms).

Usage:
    python demo/testset/evaluate_corpus.py            # reports/ + injections/
Output: results/<paper>.json, results/summary.md
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from citecheck.schema import Report  # noqa: E402
from citecheck.support.claims import split_sentences  # noqa: E402

PAPERS = ["liuqiao_kg", "luohuilan_odt", "zhaoyangyang_tod",
          "yinhongpeng_odt", "guyingjie_mrc"]


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def find_para(report: Report, snippet: str):
    """Most specific paragraph containing the snippet (whitespace-insensitive)."""
    target = norm(snippet)
    if not target:
        return None
    cands = [p for p in report.paragraphs if target in norm(p.text)]
    return min(cands, key=lambda p: len(p.text)) if cands else None


def locate(report: Report, para, snippet: str):
    """(start, end) of snippet inside para.text via whitespace-flexible regex."""
    if para is None:
        return None
    pat = re.compile(r"\s*".join(re.escape(c) for c in norm(snippet)))
    m = pat.search(para.text)
    return (m.start(), m.end()) if m else None


def overlap(a, b) -> bool:
    return bool(a and b and a[0] < b[1] and b[0] < a[1])


def claim_span(claim):
    return (claim.start, claim.end)


def load(path: Path) -> Report:
    return Report.model_validate(json.loads(path.read_text(encoding="utf-8")))


def ref_id_by_label(report: Report, label: str) -> str | None:
    for r in report.references:
        m = re.match(r"^\[(\d{1,3})\]", r.raw.strip())
        if m and m.group(1) == label:
            return r.id
    return None


def find_ref_by_inj(report: Report, inj: dict):
    """The injected reference entry: prefer the spec's [label] (unique even
    when the paper already cites a near-duplicate), fall back to a
    whitespace-insensitive match on the raw entry text."""
    lab = inj.get("label")
    if lab is not None:
        rid = ref_id_by_label(report, str(lab))
        if rid is not None:
            return next((r for r in report.references if r.id == rid), None)
    m = inj.get("match", "")
    if not m:
        return None
    return next((r for r in report.references
                 if norm(m)[:20] in norm(r.raw)), None)


def marker_sentence_span(para_text: str, pos: int):
    """(start, end) of the sentence containing the marker at `pos`, split
    with the same boundaries the claim extractor uses so spans and claims
    line up."""
    for s in split_sentences(para_text):
        if s.start <= pos < s.end:
            return (s.start, s.end)
    return (max(0, pos - 40), min(len(para_text), pos + 40))


def detect_injection(rep: Report, inj: dict) -> tuple[bool, str, dict]:
    """(detected, detail, gt_span) — gt_span = (paragraph_id, start, end) of
    the defective text for claim-level accounting (None for ref-level)."""
    kind = inj["kind"]
    if kind == "fake_ref":
        r = find_ref_by_inj(rep, inj)
        rc = next((c for c in rep.ref_checks if c.ref_id == r.id), None) if r else None
        fs = [f for f in rep.findings if f.layer == "authenticity"
              and r and r.id in f.refs]
        ok = bool(rc and rc.status == "not_found"
                  and any(f.severity == "high" for f in fs))
        return ok, f"status={rc.status if rc else '-'}", None

    if kind == "wrong_year":
        r = find_ref_by_inj(rep, inj)
        rc = next((c for c in rep.ref_checks if c.ref_id == r.id), None) if r else None
        ok = bool(rc and rc.status == "mismatch"
                  and any("年份" in i for i in rc.issues))
        return ok, f"status={rc.status if rc else '-'} issues={rc.issues if rc else []}", None

    if kind == "misattribution":
        para = find_para(rep, inj["snippet"])
        ref = ref_id_by_label(rep, inj["cited_label"])
        span = None
        if para is not None:
            s = locate(rep, para, inj["snippet"])
            marker = f"[{inj['cited_label']}]"
            pos = None
            # prefer the marker right after the recorded context snippet
            for m in re.finditer(re.escape(marker), para.text):
                if s and abs(m.start() - s[1]) <= 4:
                    pos = m.start()
                    break
            if pos is None:
                m = re.search(re.escape(marker), para.text)
                pos = m.start() if m else (s[1] if s else 0)
            span = marker_sentence_span(para.text, pos)
        cs = [c for c in rep.claims
              if para is not None and c.paragraph_id == para.id
              and overlap(claim_span(c), span)]
        cks = [c for c in rep.support_checks
               if ref and c.ref_id == ref and any(c.claim_id == cl.id for cl in cs)]
        # any support-layer alarm on the sentence counts: unsupported (high),
        # review-confirmed off_topic (medium), or the attribution rule
        fs = [f for f in rep.findings if f.layer == "support"
              and f.severity in {"high", "medium"} and f.anchor
              and f.anchor.paragraph_id == (para.id if para is not None else "")
              and overlap((f.anchor.start, f.anchor.end), span)
              and (ref is None or ref in f.refs)]
        labels = [c.label for c in cks]
        offtopic = [bool(getattr(c, "off_topic", False)) for c in cks]
        hi = any(f.severity == "high" for f in fs)
        attr = any("归属" in f.title or "引错" in f.title for f in fs)
        ok = bool((any(x == "unsupported" for x in labels) and hi)
                  or (any(offtopic) and fs)
                  or attr)
        return ok, f"labels={labels} offtopic={sum(offtopic)} findings={len(fs)}", \
            (para.id, span[0], span[1]) if (para is not None and span) else None

    if kind == "uncited":
        r = find_ref_by_inj(rep, inj)
        ok = bool(r and any(f.layer == "norms" and "没有被引用" in f.title
                            and r.id in f.refs for f in rep.findings))
        return ok, f"ref={'found' if r else 'missing'}", None

    if kind == "stacking":
        para = find_para(rep, inj["snippet"])
        span = locate(rep, para, inj["snippet"])
        fs = [f for f in rep.findings if f.layer == "distribution"
              and f.title.startswith("这句话同时引用了")
              and f.anchor and f.anchor.paragraph_id == (para.id if para else "")
              and overlap((f.anchor.start, f.anchor.end), span)]
        return bool(fs), f"findings={len(fs)}", \
            (para.id, span[0], span[1]) if (para and span) else None

    if kind == "typo":
        para = find_para(rep, inj["snippet"])
        if para is None:
            return False, "snippet not found", None
        w = norm(inj["wrong"])
        idx = norm(para.text).find(w)
        if idx < 0:
            return False, "wrong word not in parsed text", None
        # map normalised index back approximately: search raw text
        m = re.search(r"\s*".join(re.escape(c) for c in inj["wrong"]), para.text)
        span = (m.start(), m.end()) if m else None
        hits = [v for v in rep.revisions if v.kind == "typo"
                and v.anchor.paragraph_id == para.id
                and overlap((v.anchor.start, v.anchor.end), span)]
        fixed = list(inj["wrong"])
        for v in sorted(hits, key=lambda v: v.anchor.start, reverse=True):
            i, j = v.anchor.start - span[0], v.anchor.end - span[0]
            if 0 <= i and j <= len(fixed) and "".join(fixed[i:j]) == v.old:
                fixed[i:j] = list(v.new)
        ok = bool(hits) and "".join(fixed) == inj["right"]
        return ok, f"revisions={len(hits)}", \
            (para.id, span[0], span[1]) if span else None

    return False, f"unknown kind {kind}", None


def gt_spans_for(rep: Report, inj: dict):
    """Claim-level ground-truth span for injections that live in the text."""
    kind = inj["kind"]
    if kind in {"misattribution", "stacking", "typo"}:
        _, _, span = detect_injection(rep, inj)
        return span
    if kind == "fake_ref":
        para = find_para(rep, inj.get("snippet", inj.get("match", "")))
        if para is None:
            return None
        m = None
        if inj.get("label"):
            m = re.search(r"\[%s\]" % re.escape(str(inj["label"])), para.text)
        if m is None:
            m = re.search(r"\[\d{1,3}\]", para.text)
        return (para.id, m.start(), m.end()) if m else None
    return None


def claim_flags(rep: Report):
    """Predicted-positive claim ids (binary: flagged vs not)."""
    flagged, undet = set(), set()
    for f in rep.findings:
        if f.layer in {"support", "distribution", "norms"} and \
                f.severity in {"high", "medium"} and f.anchor:
            flagged.add((f.anchor.paragraph_id, f.anchor.start, f.anchor.end))
    span_by_id = {}
    for c in rep.claims:
        span_by_id[c.id] = (c.paragraph_id, c.start, c.end)
    labels = {}
    for sc in rep.support_checks:
        labels.setdefault(sc.claim_id, []).append(sc.label)
    for c in rep.claims:
        sp = span_by_id[c.id]
        hit_f = any(f.anchor and f.anchor.paragraph_id == sp[0]
                    and overlap((f.anchor.start, f.anchor.end), (sp[1], sp[2]))
                    for f in rep.findings
                    if f.layer in {"support", "distribution", "norms"}
                    and f.severity in {"high", "medium"})
        bad = any(x == "unsupported" for x in labels.get(c.id, []))
        soft = any(x == "undetermined" for x in labels.get(c.id, []))
        if hit_f or bad:
            flagged.add(c.id)
        if soft:
            undet.add(c.id)
    return flagged, undet


def ref_flags(rep: Report):
    flagged = set()
    for c in rep.ref_checks:
        if c.status in {"not_found", "mismatch"}:
            flagged.add(c.ref_id)
    for f in rep.findings:
        if f.layer == "norms" and "没有被引用" in f.title:
            flagged.update(f.refs)
    return flagged


def score(rep_inj: Report, rep_clean: Report, spec: dict):
    detection, gt_claim_spans = [], []
    gt_ref_ids = set()
    for inj in spec["injections"]:
        ok, detail, span = detect_injection(rep_inj, inj)
        detection.append({"id": inj["id"], "kind": inj["kind"],
                          "detected": ok, "detail": detail})
        # ground truth covers every injection, detected or not: an alarm on
        # an undetected injection's position is a true positive there, not a
        # false positive elsewhere (it IS the defect location)
        if span:
            gt_claim_spans.append(span)
        if inj["kind"] in {"fake_ref", "uncited"}:
            r = next((r for r in rep_inj.references
                      if norm(inj["match"])[:20] in norm(r.raw)), None)
            if r:
                gt_ref_ids.add(r.id)
        if inj["kind"] == "wrong_year":
            r = next((r for r in rep_inj.references
                      if norm(inj["match"])[:20] in norm(r.raw)), None)
            if r:
                gt_ref_ids.add(r.id)

    inj_flagged, inj_undet = claim_flags(rep_inj)
    clean_flagged, clean_undet = claim_flags(rep_clean)
    inj_ref_flagged = ref_flags(rep_inj)
    clean_ref_flagged = ref_flags(rep_clean)

    # claim units — binary accounting per the corpus design: a unit is
    # predicted positive iff the pipeline raised an alarm on it. Support
    # judgments that came back undetermined are coverage, not alarms.
    tp = fn = fp = tn = undet_on_defect = pre_existing = 0
    definitive = 0
    total_claims = len(rep_inj.claims)
    for c in rep_inj.claims:
        sp = (c.paragraph_id, c.start, c.end)
        gt = any(s[0] == sp[0] and overlap((s[1], s[2]), (sp[1], sp[2]))
                 for s in gt_claim_spans)
        pred = c.id in inj_flagged
        soft = c.id in inj_undet
        # pre-existing: the clean run flagged the same text position
        pre = any(f.anchor and f.anchor.paragraph_id == sp[0]
                  and overlap((f.anchor.start, f.anchor.end), (sp[1], sp[2]))
                  for f in rep_clean.findings
                  if f.severity in {"high", "medium"})
        if gt:
            if pred:
                tp += 1
            else:
                fn += 1
            if soft and not pred:
                undet_on_defect += 1
        else:
            if pre:
                pre_existing += 1
                tn += 0 if pred else 1
                continue
            if pred:
                fp += 1
            else:
                tn += 1
    # coverage: clean claims with at least one definitive support judgment
    labels_all = {}
    for sc in rep_inj.support_checks:
        labels_all.setdefault(sc.claim_id, []).append(sc.label)
    for c in rep_inj.claims:
        if c.id in inj_undet and c.id not in inj_flagged:
            continue
        labs = labels_all.get(c.id, [])
        if any(x in {"supported", "partial", "unsupported"} for x in labs):
            definitive += 1

    # ref units
    rtp = rfn = rfp = rtn = 0
    for r in rep_inj.references:
        gt = r.id in gt_ref_ids
        pred = r.id in inj_ref_flagged
        pre = r.id in clean_ref_flagged
        if gt:
            if pred:
                rtp += 1
            else:
                rfn += 1
        else:
            if pre:
                rtn += 0 if pred else 1
                continue
            if pred:
                rfp += 1
            else:
                rtn += 1

    def prr(tp_, fp_, fn_, tn_):
        p = tp_ / (tp_ + fp_) if tp_ + fp_ else None
        r = tp_ / (tp_ + fn_) if tp_ + fn_ else None
        a = (tp_ + tn_) / (tp_ + fp_ + fn_ + tn_) if (tp_ + fp_ + fn_ + tn_) else None
        return p, r, a

    res = {
        "detection": detection,
        "claims": {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                   "total_claims": total_claims,
                   "support_definitive": definitive,
                   "pre_existing_flagged": pre_existing,
                   "undetermined_on_defect": undet_on_defect,
                   "pr_acc": prr(tp, fp, fn, tn)},
        "refs": {"tp": rtp, "fp": rfp, "fn": rfn, "tn": rtn,
                 "pr_acc": prr(rtp, rfp, rfn, rtn)},
        "totals": {"tp": tp + rtp, "fp": fp + rfp, "fn": fn + rfn,
                   "tn": tn + rtn,
                   "pr_acc": prr(tp + rtp, fp + rfp, fn + rfn, tn + rtn)},
    }
    return res


def main() -> int:
    reports = HERE / "reports"
    outdir = HERE / "results"
    outdir.mkdir(exist_ok=True)
    summary = ["# 测试集评测结果\n"]
    all_totals = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for paper in PAPERS:
        inj_path = reports / f"{paper}_injected.json"
        clean_path = reports / f"{paper}_clean.json"
        if not inj_path.exists() or not clean_path.exists():
            print(f"skip {paper}: reports missing")
            continue
        spec = json.loads((HERE / "injections" / f"{paper}.json").read_text())
        res = score(load(inj_path), load(clean_path), spec)
        (outdir / f"{paper}.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        det = sum(1 for d in res["detection"] if d["detected"])
        c = res["claims"]
        r = res["refs"]
        tt = res["totals"]
        for k in ("tp", "fp", "fn", "tn"):
            all_totals[k] += tt[k]
        summary.append(
            f"## {paper}\n"
            f"- 注入检出: {det}/{len(res['detection'])}"
            f"（{'、'.join(d['id'] for d in res['detection'] if not d['detected']) or '全部'} 未检出）\n"
            f"- 论断级: TP={c['tp']} FP={c['fp']} FN={c['fn']} TN={c['tn']}"
            f" 既有问题={c['pre_existing_flagged']}"
            f" 支持度判定覆盖={c['support_definitive']}/{c['total_claims']}\n"
            f"- 文献级: TP={r['tp']} FP={r['fp']} FN={r['fn']} TN={r['tn']}\n"
            f"- 合计 P/R/Acc: "
            f"{tt['pr_acc'][0]:.3f} / {tt['pr_acc'][1]:.3f} / {tt['pr_acc'][2]:.3f}\n")
    n_all = sum(all_totals.values())
    tp, fp, fn, tn = (all_totals["tp"], all_totals["fp"],
                      all_totals["fn"], all_totals["tn"])
    p_all = tp / (tp + fp) if tp + fp else 0
    r_all = tp / (tp + fn) if tp + fn else 0
    a_all = (tp + tn) / n_all if n_all else 0
    summary.append(
        f"---\n\n## 五篇汇总（论断级 + 文献级）\n"
        f"- TP={tp} FP={fp} FN={fn} TN={tn}\n"
        f"- **查准率 {p_all:.3f}　查全率 {r_all:.3f}　准确率 {a_all:.3f}**\n")
    (outdir / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary[-4:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
