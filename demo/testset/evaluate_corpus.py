"""F8: score the eval corpus — per-injection detection + per-unit P/R/Acc.

Unit of measurement (per the corpus design): the citing claim (一条引用句) and
the reference. For every injected manuscript this script

  1. checks each injection against the pipeline report using the same
     detection rules as demo/evaluate.py (not relaxed); a misattribution
     counts as detected when the pipeline raised ANY support-layer alarm on
     the swapped marker's sentence that names the swapped-in reference —
     unsupported (high), review-confirmed off_topic (medium) or the
     attribution-consistency rule (medium),
  2. maps each injection to the one unit it lives in (claim / reference /
     uncovered sentence) — TP or FN by its own detection rule — and treats
     every other unit as a negative, predicted positive iff the pipeline
     raised any high/medium alarm on it (findings, unsupported labels,
     not_found / mismatch status, typo revisions),
  3. splits negative alarms into new ones and ones the CLEAN run also raised
     on the same text (matched by text, not offsets),
  4. reports precision two ways: lenient leaves clean-run alarms out as the
     paper's own defects, strict counts them as false positives. Clean-run
     alarms are not hand-checked, so the true precision lies in between.

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
              and ref is not None and ref in f.refs]
        labels = [c.label for c in cks]
        offtopic = [bool(getattr(c, "off_topic", False)) for c in cks]
        hi = any(f.severity == "high" for f in fs)
        # the attribution rule only — the off-topic title also says
        # "可能引错了" and is already covered by the off_topic flag
        attr = any("归属" in f.title for f in fs)
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


def _sentence_key(text: str, s: int, e: int) -> tuple[int, int]:
    for sent in split_sentences(text):
        if sent.start <= s < sent.end:
            return (sent.start, max(sent.end, e))
    return (s, e)


class Units:
    """Every scored unit of one report: each claim (引用句), each reference
    entry, plus 'span' units — the sentence around an alarm or an injected
    defect that no claim covers (a typo revision in prose without a
    citation). Each unit carries a text key, so a clean-run unit and the
    same unit in the injected run line up even when offsets shift."""

    def __init__(self, rep: Report):
        self.rep = rep
        self.paras = {p.id: p for p in rep.paragraphs}
        self.ref_by_para = {r.paragraph_id: r.id for r in rep.references
                            if getattr(r, "paragraph_id", None)}
        self.claims_by_para: dict[str, list] = {}
        for c in rep.claims:
            self.claims_by_para.setdefault(c.paragraph_id, []).append(c)
        self.alarms: dict[tuple, list[str]] = {}  # unit -> alarm labels
        self._collect()

    def units_at(self, pid: str, s: int, e: int) -> list[tuple]:
        if pid in self.ref_by_para:
            return [("ref", self.ref_by_para[pid])]
        cs = [("claim", c.id) for c in self.claims_by_para.get(pid, [])
              if overlap((c.start, c.end), (s, e))]
        if cs:
            return cs
        para = self.paras.get(pid)
        a, b = _sentence_key(para.text, s, e) if para else (s, e)
        return [("span", pid, a, b)]

    def key(self, unit: tuple) -> str:
        if unit[0] == "ref":
            r = next(r for r in self.rep.references if r.id == unit[1])
            return "ref:" + norm(r.raw)
        if unit[0] == "claim":
            c = next(c for c in self.rep.claims if c.id == unit[1])
            return "txt:" + norm(c.text)
        para = self.paras[unit[1]]
        return "txt:" + norm(para.text[unit[2]:unit[3]])

    def _add(self, unit, label):
        self.alarms.setdefault(unit, []).append(label)

    def _collect(self):
        rep = self.rep
        for f in rep.findings:
            if f.severity not in {"high", "medium"}:
                continue
            label = f"{f.layer}:{re.sub(r'[0-9]+', 'N', f.title)}"
            if f.anchor:
                for u in self.units_at(f.anchor.paragraph_id,
                                       f.anchor.start, f.anchor.end):
                    self._add(u, label)
            elif f.refs:
                for rid in f.refs:
                    self._add(("ref", rid), label)
        for c in rep.ref_checks:
            if c.status in {"not_found", "mismatch"}:
                self._add(("ref", c.ref_id), f"status:{c.status}")
        claims = {c.id: c for c in rep.claims}
        for sc in rep.support_checks:
            if sc.label == "unsupported" and sc.claim_id in claims:
                self._add(("claim", sc.claim_id), "label:unsupported")
        for v in rep.revisions:
            if v.kind == "typo":
                for u in self.units_at(v.anchor.paragraph_id,
                                       v.anchor.start, v.anchor.end):
                    self._add(u, "revision:typo")

    def all_units(self) -> set[tuple]:
        return ({("claim", c.id) for c in self.rep.claims}
                | {("ref", r.id) for r in self.rep.references}
                | set(self.alarms))


def injection_location(rep: Report, U: Units, inj: dict, span):
    """Where an injection lives: ("ref", id) for entry-level defects, else
    (paragraph_id, start, end) of the whole sentence — claims are often
    clauses, and every clause and alarm in that sentence belongs to the
    one data point the injection is."""
    if inj["kind"] in {"fake_ref", "uncited", "wrong_year"}:
        r = find_ref_by_inj(rep, inj)
        return ("ref", r.id) if r else None
    if span is None:
        return None
    pid, a, b = span
    return (pid, *_sentence_key(U.paras[pid].text, a, b))


def fake_sentence_location(rep: Report, inj: dict):
    """The sentence the injector wrote to cite a fake entry: new text whose
    only defect is the fake reference (scored at the entry), so it is
    neither a positive nor a negative."""
    para = find_para(rep, inj.get("snippet", ""))
    loc = locate(rep, para, inj.get("snippet", ""))
    if para is None or loc is None:
        return None
    return (para.id, *_sentence_key(para.text, loc[0], loc[1]))


def unit_location(U: Units, u: tuple):
    if u[0] == "ref":
        return u
    if u[0] == "claim":
        c = next(c for c in U.rep.claims if c.id == u[1])
        return (c.paragraph_id, c.start, c.end)
    return u[1:]


def _hits(loc, locs) -> bool:
    if loc[0] == "ref":
        return loc in locs
    return any(x[0] == loc[0] and x[0] != "ref"
               and overlap((loc[1], loc[2]), (x[1], x[2])) for x in locs)


def score(rep_inj: Report, rep_clean: Report, spec: dict):
    Ui, Uc = Units(rep_inj), Units(rep_clean)
    clean_flagged = {Uc.key(u) for u in Uc.alarms}

    detection, gt_locs, excluded = [], [], []
    for inj in spec["injections"]:
        ok, detail, span = detect_injection(rep_inj, inj)
        loc = injection_location(rep_inj, Ui, inj, span)
        detection.append({"id": inj["id"], "kind": inj["kind"],
                          "detected": ok, "detail": detail,
                          "located": loc is not None})
        if loc:
            gt_locs.append(loc)
        if inj["kind"] == "fake_ref":
            fl = fake_sentence_location(rep_inj, inj)
            if fl:
                excluded.append(fl)
        if inj["kind"] == "misattribution":
            # the swap may leave the original entry uncited: a true
            # consequence of the injection, neither positive nor negative
            rid = ref_id_by_label(rep_inj, inj["intended_label"])
            if rid:
                excluded.append(("ref", rid))

    # one data point per injection: the injection's own detection rule
    # decides the positive (an unrelated alarm on the same sentence is not
    # a detection); every other unit is a negative, predicted positive iff
    # the pipeline raised any high/medium alarm on it
    tp = sum(1 for d in detection if d["detected"])
    fn = len(detection) - tp
    fp = tn = pre = 0
    fp_units, pre_units = [], []
    n_excluded = 0
    for u in Ui.all_units():
        loc = unit_location(Ui, u)
        if _hits(loc, gt_locs):
            continue
        if _hits(loc, excluded):
            n_excluded += 1
            continue
        if u not in Ui.alarms:
            tn += 1
        elif Ui.key(u) in clean_flagged:
            pre += 1
            pre_units.append((u, Ui.alarms[u]))
        else:
            fp += 1
            fp_units.append((u, Ui.alarms[u]))

    labels = {}
    for sc in rep_inj.support_checks:
        labels.setdefault(sc.claim_id, []).append(sc.label)
    definitive = sum(1 for c in rep_inj.claims
                     if any(x in {"supported", "partial", "unsupported"}
                            for x in labels.get(c.id, [])))

    def prr(tp_, fp_, fn_, tn_):
        n = tp_ + fp_ + fn_ + tn_
        return (tp_ / (tp_ + fp_) if tp_ + fp_ else None,
                tp_ / (tp_ + fn_) if tp_ + fn_ else None,
                (tp_ + tn_) / n if n else None)

    def describe(items):
        out = []
        for u, al in items:
            txt = Ui.key(u)[4:64]
            out.append({"unit": list(u), "alarms": sorted(set(al)), "text": txt})
        return out

    return {
        "detection": detection,
        "counts": {"tp": tp, "fn": fn, "fp_new": fp, "pre_existing": pre,
                   "tn": tn, "excluded": n_excluded,
                   "claims": len(rep_inj.claims),
                   "refs": len(rep_inj.references),
                   "support_definitive": definitive},
        # lenient: alarms the clean run also raised are taken as the
        # paper's own defects and left out; strict: they count as FP
        "lenient": prr(tp, fp, fn, tn),
        "strict": prr(tp, fp + pre, fn, tn),
        "fp_units": describe(fp_units),
        "pre_existing_units": describe(pre_units),
    }


def _fmt(x):
    return "-" if x is None else f"{x:.3f}"


def main() -> int:
    reports = HERE / "reports"
    outdir = HERE / "results"
    outdir.mkdir(exist_ok=True)
    tot = {"tp": 0, "fn": 0, "fp_new": 0, "pre_existing": 0, "tn": 0}
    by_kind: dict[str, list[int]] = {}
    pre_types: dict[str, int] = {}
    fp_types: dict[str, int] = {}
    cover = [0, 0]
    rows = []
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
        c = res["counts"]
        for k in tot:
            tot[k] += c[k]
        cover[0] += c["support_definitive"]
        cover[1] += c["claims"]
        for d in res["detection"]:
            k = by_kind.setdefault(d["kind"], [0, 0])
            k[0] += d["detected"]
            k[1] += 1
        for key, store in (("pre_existing_units", pre_types), ("fp_units", fp_types)):
            for u in res[key]:
                for a in u["alarms"]:
                    store[a] = store.get(a, 0) + 1
        missed = "、".join(d["id"] for d in res["detection"] if not d["detected"]) or "无"
        rows.append(
            f"| {paper} | {c['tp']}/{c['tp'] + c['fn']} | {missed} | {c['fp_new']} | "
            f"{c['pre_existing']} | {c['tn']} | {_fmt(res['lenient'][0])} | "
            f"{_fmt(res['strict'][0])} | {_fmt(res['lenient'][1])} |")

    tp, fn, fp, pre, tn = (tot[k] for k in ("tp", "fn", "fp_new", "pre_existing", "tn"))
    n_len, n_str = tp + fn + fp + tn, tp + fn + fp + pre + tn
    p_len = tp / (tp + fp) if tp + fp else 0
    p_str = tp / (tp + fp + pre) if tp + fp + pre else 0
    rec = tp / (tp + fn) if tp + fn else 0
    out = ["# 测试集评测结果\n",
           "数据点：一条引用句或一条参考文献为一个单元。每处注入落在一个单元上，"
           "按该注入自己的检出规则判定 TP/FN；其余单元为负例，体检在其上报出任一"
           "高/中严重度问题（含错别字修订）即为阳性。\n",
           "宽口径把干净稿也报出的问题当作原文自身的问题剔除；严口径把它们计为误报。"
           "两者之间的差距来自干净稿报警，尚未人工核对，真实查准率落在两个口径之间。\n",
           "## 分篇\n",
           "| 论文 | 检出 | 未检出 | 新增误报 | 干净稿既有报警 | TN | 查准率（宽） | 查准率（严） | 查全率 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- |", *rows, "",
           "## 按注入类型\n", "| 类型 | 检出 |", "| --- | --- |",
           *[f"| {k} | {v[0]}/{v[1]} |" for k, v in by_kind.items()], "",
           "## 五篇汇总\n",
           f"- TP={tp} FN={fn} 新增误报={fp} 干净稿既有报警={pre} TN={tn}",
           f"- 查全率 **{rec:.3f}**",
           f"- 查准率 宽 **{p_len:.3f}**　严 **{p_str:.3f}**",
           f"- 准确率 宽 {(tp + tn) / n_len:.3f}　严 {(tp + tn) / n_str:.3f}"
           "（负例占绝大多数，准确率主要反映 TN 规模）",
           f"- 支持度判定覆盖：{cover[0]}/{cover[1]} 条引用句拿到确定判断"
           f"（{cover[0] / cover[1]:.1%}），其余为无法判断\n",
           "## 新增误报的报警类型\n",
           *[f"- {k}：{v}" for k, v in sorted(fp_types.items(), key=lambda x: -x[1])], "",
           "## 干净稿既有报警的类型（严口径多出的部分）\n",
           *[f"- {k}：{v}" for k, v in sorted(pre_types.items(), key=lambda x: -x[1])], ""]
    (outdir / "summary.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
