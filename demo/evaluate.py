"""T11c: score the real pipeline output on demo_paper.docx against
injections.json, and verify the export accept-all reorder guarantee.

Usage:
    python demo/evaluate.py [report.json] [demo_paper.docx]
    -> writes demo/eval_result.json

Detection rules per injection kind:
  fake_ref       RefCheck.status == not_found + a high authenticity finding
  wrong_year     RefCheck.status == mismatch + an issue containing 年份
  misattribution a SupportCheck on the injected claim -> cited ref labelled
                 unsupported + a high support finding anchoring that claim
  uncited        a norms finding "这篇参考文献在正文中没有被引用" on the ref
  stacking       a distribution finding "这句话同时引用了 N 篇文献" whose
                 anchor overlaps the injected sentence
  typo           a typo Revision old->new anchored in the injected sentence;
                 protected terms must not be overlapped by any revision
  reorder        export_report() succeeds — its built-in self-check asserts
                 reject-all == original text and accept-all produces the
                 first-appearance ref order with markers resolving to the
                 same works (raises otherwise)
Acceptance (PLAN T11): >= 8/10 detected AND zero high-severity findings
that do not correspond to an injection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "backend"))

from citecheck.export.writer import export_report  # noqa: E402
from citecheck.schema import Report  # noqa: E402

REPORT_JSON = HERE / "demo_report.json"
DOCX = HERE / "demo_paper.docx"
SPEC_JSON = HERE / "injections.json"
RESULT_JSON = HERE / "eval_result.json"
EXPORT_DIR = HERE / "export"


def _ov(a_s: int, a_e: int, b_s: int, b_e: int) -> bool:
    return a_s < b_e and b_s < a_e


def _ref_label(raw: str) -> str:
    head = raw.lstrip()[:8]
    end = head.find("]")
    return head[1:end] if head.startswith("[") and end > 0 else ""


def main() -> int:
    report_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPORT_JSON
    docx = Path(sys.argv[2]) if len(sys.argv) > 2 else DOCX
    report = Report.model_validate(
        json.loads(report_path.read_text(encoding="utf-8")))
    spec = json.loads(SPEC_JSON.read_text(encoding="utf-8"))

    paras = report.paragraphs
    ref_by_id = {r.id: r for r in report.references}
    rc_by_id = {rc.ref_id: rc for rc in report.ref_checks}
    claims = report.claims
    findings = report.findings

    def para_with(snippet: str):
        return next((p for p in paras if snippet in p.text), None)

    def ref_matching(match: str):
        return next((r for r in report.references if match in r.raw), None)

    def ref_by_label(label: str):
        return next((r for r in report.references
                     if _ref_label(r.raw) == str(label)), None)

    expected_high: set[str] = set()   # finding ids explained by injections
    results: list[dict] = []

    for inj in spec["injections"]:
        kind, iid = inj["kind"], inj["id"]
        ok, detail = False, ""

        if kind == "fake_ref":
            r = ref_matching(inj["match"])
            rc = rc_by_id.get(r.id) if r else None
            fs = [f for f in findings if f.layer == "authenticity"
                  and r and r.id in f.refs]
            expected_high.update(f.id for f in fs)
            ok = bool(rc and rc.status == "not_found"
                      and any(f.severity == "high" for f in fs))
            detail = (f"ref={r.id if r else '?'} "
                      f"status={rc.status if rc else '-'}")

        elif kind == "wrong_year":
            r = ref_matching(inj["match"])
            rc = rc_by_id.get(r.id) if r else None
            fs = [f for f in findings if f.layer == "authenticity"
                  and r and r.id in f.refs]
            expected_high.update(f.id for f in fs)
            year_hit = bool(rc and any("年份" in i for i in rc.issues))
            ok = bool(rc and rc.status == "mismatch" and year_hit)
            detail = (f"ref={r.id if r else '?'} "
                      f"status={rc.status if rc else '-'} "
                      f"issues={rc.issues if rc else []}")

        elif kind == "misattribution":
            p = para_with(inj["snippet"])
            ref = ref_by_label(inj["cited_label"])
            if p:
                s = p.text.find(inj["snippet"])
                span = (s, s + len(inj["snippet"]))
                cs = [c for c in claims if c.paragraph_id == p.id
                      and _ov(c.start, c.end, *span)]
                cks = [c for c in report.support_checks
                       if c.ref_id == (ref.id if ref else "")
                       and any(c.claim_id == cl.id for cl in cs)]
                fs = [f for f in findings
                      if f.layer == "support" and f.severity == "high"
                      and f.anchor and f.anchor.paragraph_id == p.id
                      and _ov(f.anchor.start, f.anchor.end, *span)]
                expected_high.update(f.id for f in fs)
                ok = bool(any(c.label == "unsupported" for c in cks) and fs)
                detail = (f"para={p.id} ref={ref.id if ref else '?'} "
                          f"labels={[c.label for c in cks]} "
                          f"findings={len(fs)}")
            else:
                detail = "snippet not in any paragraph"

        elif kind == "uncited":
            r = ref_matching(inj["match"])
            ok = bool(r and any(
                f.layer == "norms" and "没有被引用" in f.title
                and r.id in f.refs for f in findings))
            detail = f"ref={r.id if r else '?'}"

        elif kind == "stacking":
            p = para_with(inj["snippet"])
            if p:
                s = p.text.find(inj["snippet"])
                span = (s, s + len(inj["snippet"]))
                fs = [f for f in findings
                      if f.layer == "distribution"
                      and f.title.startswith("这句话同时引用了")
                      and f.anchor and f.anchor.paragraph_id == p.id
                      and _ov(f.anchor.start, f.anchor.end, *span)]
                ok = bool(fs)
                detail = f"para={p.id} findings={[f.title for f in fs]}"
            else:
                detail = "snippet not in any paragraph"

        elif kind == "typo":
            p = para_with(inj["snippet"])
            if p:
                ts = p.text.find(inj["wrong"])
                hit = []
                if ts >= 0:
                    wspan = (ts, ts + len(inj["wrong"]))
                    # revisions anchored INSIDE the injected word whose
                    # combined application yields the intended spelling
                    # count — the pipeline often revises only the
                    # misspelt fragment ('Retreival' of
                    # 'Retreival-augmented'), not the whole word
                    hit = [v for v in report.revisions
                           if v.kind == "typo"
                           and v.anchor.paragraph_id == p.id
                           and _ov(v.anchor.start, v.anchor.end, *wspan)]
                    fixed = list(inj["wrong"])
                    for v in sorted(hit, key=lambda v: v.anchor.start,
                                    reverse=True):
                        i, j = v.anchor.start - ts, v.anchor.end - ts
                        if 0 <= i and j <= len(fixed) \
                                and "".join(fixed[i:j]) == v.old:
                            fixed[i:j] = list(v.new)
                    ok = bool(hit) and "".join(fixed) == inj["right"]
                detail = (f"para={p.id} revisions="
                          f"{len(hit)} old={inj['wrong']!r}")
                for term in inj.get("protected", []):
                    ts = p.text.find(term)
                    if ts < 0:
                        continue
                    bad = [v for v in report.revisions
                           if v.anchor.paragraph_id == p.id
                           and _ov(v.anchor.start, v.anchor.end,
                                   ts, ts + len(term))]
                    if bad:
                        ok = False
                        detail += f" | PROTECTED term {term!r} touched " \
                                  f"by {bad[0].kind}"
            else:
                detail = "snippet not in any paragraph"

        results.append({"id": iid, "kind": kind, "detected": ok,
                        "detail": detail})

    # ---- reorder: export + built-in accept/reject self-check ----------
    EXPORT_DIR.mkdir(exist_ok=True)
    out_docx = EXPORT_DIR / "demo_paper_体检.docx"
    try:
        export_report(docx, report, out_docx)
        results.append({"id": "reorder", "kind": "reorder",
                        "detected": True,
                        "detail": f"exported {out_docx.name}; self-check "
                                  "(reject=orig, accept=first-appearance "
                                  "order) passed"})
    except Exception as e:  # noqa: BLE001
        results.append({"id": "reorder", "kind": "reorder",
                        "detected": False, "detail": f"export failed: {e}"})

    # ---- high-severity false positives --------------------------------
    injected = {i["id"] for i in results}
    unmatched_high = [
        {"id": f.id, "layer": f.layer, "title": f.title,
         "anchor": f.anchor.model_dump() if f.anchor else None,
         "refs": f.refs}
        for f in findings if f.severity == "high" and f.id not in expected_high
    ]

    n10 = [r for r in results if r["id"] != "reorder"]
    detected = sum(1 for r in n10 if r["detected"])
    summary = {
        "detected": f"{detected}/{len(n10)}",
        "reorder_check": next(r["detected"] for r in results
                              if r["id"] == "reorder"),
        "unmatched_high_findings": len(unmatched_high),
        "passed": detected >= 8 and not unmatched_high
                  and all(r["detected"] for r in results
                          if r["id"] == "reorder"),
        "high_findings": [{"id": f.id, "layer": f.layer, "title": f.title,
                           "refs": f.refs}
                          for f in findings if f.severity == "high"],
        "unmatched_high": unmatched_high,
        "severity_counts": {
            s: sum(1 for f in findings if f.severity == s)
            for s in ("high", "medium", "low")},
        "results": results,
    }
    RESULT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
