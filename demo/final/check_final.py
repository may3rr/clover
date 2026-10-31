"""逐条核对演示稿里的注入是否都被挑出来，并列出注入以外的报警。

    python demo/final/check_final.py demo/final/runs/demo_v1.json

退出码 0 表示全部检出。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main() -> int:
    rep = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    spec = json.loads((HERE / "injections.json").read_text(encoding="utf-8"))
    paras = {p["id"]: p["text"] for p in rep["paragraphs"]}
    by_label = {}
    for r in rep["references"]:
        m = re.match(r"^\[(\d{1,3})\]", r["raw"].strip())
        if m:
            by_label[m.group(1)] = r["id"]
    checks = {c["ref_id"]: c for c in rep["ref_checks"]}
    claims = {c["id"]: c for c in rep["claims"]}

    def finding_text(f) -> str:
        a = f.get("anchor") or {}
        return squash(paras.get(a.get("paragraph_id"), ""))

    def findings_at(snippet: str, layer: str | None = None):
        s = squash(snippet)
        return [f for f in rep["findings"] if s in finding_text(f)
                and (layer is None or f["layer"] == layer)]

    used: set[str] = set()

    def hit(fs, why: str):
        for f in fs:
            used.add(f["id"])
        return bool(fs), why if fs else ""

    results = []
    for inj in spec["injections"]:
        k = inj["kind"]
        rid = by_label.get(inj.get("label", ""))
        ok, how = False, ""
        if k == "fake_ref":
            st = checks.get(rid, {}).get("status")
            fs = [f for f in rep["findings"] if f["layer"] == "authenticity" and rid in f["refs"]]
            ok, how = hit(fs, f"status={st}") if st in {"not_found", "mismatch"} else (False, f"status={st}")
        elif k == "wrong_year":
            c = checks.get(rid, {})
            fs = [f for f in rep["findings"] if f["layer"] == "authenticity" and rid in f["refs"]
                  and "年份" in f["detail"]]
            ok, how = hit(fs, "; ".join(c.get("issues") or []))
        elif k in {"misattribution", "number"}:
            s = squash(inj["snippet"])
            labels = [sc["label"] for sc in rep["support_checks"] if sc["ref_id"] == rid
                      and s[:12] in squash(paras.get(claims[sc["claim_id"]]["paragraph_id"], ""))]
            fs = [f for f in findings_at(inj["snippet"], "support") if rid in f["refs"]]
            ok, how = hit(fs, f"{fs[0]['title']} labels={labels}" if fs else f"labels={labels}")
        elif k == "author_swap":
            fs = [f for f in findings_at(inj["snippet"], "support") if rid in f["refs"]]
            ok, how = hit(fs, fs[0]["title"] if fs else "")
        elif k == "stacking":
            ok, how = hit([f for f in findings_at(inj["snippet"], "distribution")
                           if "同时引用" in f["title"]], "stacking")
        elif k == "duplicate":
            ok, how = hit([f for f in rep["findings"] if "重复" in f["title"] and rid in f["refs"]],
                          "duplicate")
        elif k == "uncited":
            ok, how = hit([f for f in rep["findings"] if "没有被引用" in f["title"]
                           and rid in f["refs"]], "uncited")
        elif k == "dangling":
            ok, how = hit([f for f in findings_at(inj["snippet"]) if "找不到" in f["title"]],
                          "dangling")
        elif k == "typo":
            rv = [r for r in rep["revisions"] if r["kind"] == "typo" and r["old"]
                  and r["old"] in inj["wrong"]
                  and inj["wrong"] in paras.get(r["anchor"]["paragraph_id"], "")]
            for r in rv:
                used.add(r["id"])
            ok, how = bool(rv), (f"{rv[0]['old']} -> {rv[0]['new']}" if rv else "")
        elif k == "reorder":
            rv = [r for r in rep["revisions"] if r["kind"] in {"ref_reorder", "marker_renumber"}]
            for r in rv:
                used.add(r["id"])
            ok, how = bool(rv), f"{len(rv)} 处修订"
        results.append((inj, ok, how))

    miss = 0
    for inj, ok, how in results:
        miss += not ok
        print(f"{'✓' if ok else '✗'} {inj['id']:16} {inj['layer']:4} {inj['what'][:40]:42} {how[:70]}")
    print(f"\n检出 {len(results) - miss}/{len(results)}")

    rest = [f for f in rep["findings"] if f["id"] not in used]
    print(f"\n注入以外的报警 {len(rest)} 条：")
    for f in rest:
        ctx = finding_text(f)
        print(f"  [{f['severity']:6}] {f['layer']:12} {f['title'][:30]:32} refs={f['refs']} "
              f"{ctx[:40]}")
    other_rev = [r for r in rep["revisions"] if r["id"] not in used]
    print(f"\n注入以外的修订 {len(other_rev)} 条：")
    for r in other_rev:
        print(f"  {r['kind']:16} {r['old']!r} -> {r['new']!r}")
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main())
