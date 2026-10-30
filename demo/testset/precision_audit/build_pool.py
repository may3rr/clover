"""Precision audit, step 1: pool the clean-run alarms, draw a stratified
sample, write the annotation page.

The pool is exactly the "干净稿既有报警" of evaluate_corpus.py: this script
imports its score() and takes `pre_existing_units` as is, so the counts match
results/summary*.md by construction (515 zh, 173 en for the deepseek-flash
reports). A pooled item is one scored unit (claim / reference / sentence span)
carrying one or more alarm labels; each unit goes to exactly one stratum, the
first of its labels in STRATUM_ORDER, so strata sum to the pool size.

No model is called. Context shown on the page comes from the reports and
local source files only: the PDF / HTML a Chinese manuscript was converted
from, and the LaTeX source line an English anchor already records.

Usage:
    python demo/testset/precision_audit/build_pool.py
    python demo/testset/precision_audit/build_pool.py --reports DIR --out DIR
Outputs (in --out): pool.csv, sample.json, annotate.html
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
TESTSET = HERE.parent
ROOT = TESTSET.parent.parent
sys.path.insert(0, str(TESTSET))

import evaluate_corpus as ev  # noqa: E402

SEED = 42
TARGET = {"zh": 100, "en": 60}
FLOOR = 8

# stratum priority: a unit with several alarms is filed under the first match.
# status:* and label:* always travel with their authenticity / support
# finding, so they only lead when a rerun emits them alone.
STRATUM_ORDER = [
    "authenticity:未能在数据库中找到这篇文献",
    "authenticity:文献信息与数据库记录不一致",
    "authenticity:*",
    "status:not_found",
    "status:mismatch",
    "support:被引文献不支持这条论断",
    "support:被引文献的研究内容与这条论断无关，可能引错了文献",
    "support:正文作者归属与文献作者不一致，可能引错了文献",
    "support:被引文献只部分支持这条论断",
    "support:*",
    "label:unsupported",
    "distribution:这句话同时引用了 N 篇文献",
    "distribution:*",
    "norms:*",
    "revision:typo",
    "*",
]

# source each Chinese manuscript.docx was converted from (build_docx.py)
ZH_SOURCE = {
    "liuqiao_kg": "zh_papers/liuqiao_kg/manuscript.pdf",
    "luohuilan_odt": "zh_papers/luohuilan_odt/manuscript.pdf",
    "zhaoyangyang_tod": "zh_papers/zhaoyangyang_tod/manuscript.pdf",
    "yinhongpeng_odt": "zh_pdfs/aas_yinhongpeng_2016.pdf",
    "guyingjie_mrc": "zh_html/jos_mrc_body.json",
}

SEV_RANK = {"high": 0, "medium": 1, "low": 2, "revision": 3}
EXCERPT_MAX = 6000


def stratum_rank(label: str) -> tuple[int, str]:
    for i, pat in enumerate(STRATUM_ORDER):
        if pat == label or (pat.endswith("*") and label.startswith(pat[:-1])):
            return (i, label)
    return (len(STRATUM_ORDER), label)


def stratum_of(labels: list[str]) -> str:
    return min(labels, key=stratum_rank)


# ---- source text of the original manuscript ------------------------------

def _keep(c: str) -> bool:
    # markers ([n] in docx, bare superscript digits in the PDF) and line
    # breaks differ between the two sides; match on everything else
    return not (c.isspace() or c.isdigit() or c in "[]")


class SourceText:
    """Pages of the original PDF (or HTML paragraphs), NFKC-normalised, with
    an index map from the marker/whitespace-free string back to raw text."""

    def __init__(self, path: Path):
        self.pages: list[tuple[str, str]] = []  # (where, text)
        if path.suffix == ".pdf":
            import fitz
            with fitz.open(path) as doc:
                for i, page in enumerate(doc):
                    self.pages.append((f"PDF 第 {i + 1} 页",
                                       unicodedata.normalize("NFKC", page.get_text("text"))))
            self.kind = "原 PDF"
        else:
            js = json.loads(path.read_text(encoding="utf-8"))
            for i, t in enumerate(js["paragraphs"]):
                self.pages.append((f"官网 HTML 第 {i + 1} 段", unicodedata.normalize("NFKC", t)))
            self.kind = "官网 HTML 全文"
        self.kept: list[tuple[str, list[int]]] = []
        for _, t in self.pages:
            idx = [i for i, c in enumerate(t) if _keep(c)]
            self.kept.append(("".join(t[i] for i in idx), idx))

    def locate(self, left: str, mid: str, right: str):
        """Window of the source around docx text left|mid|right."""
        lk = "".join(c for c in left if _keep(c))[-8:]
        rk = "".join(c for c in right if _keep(c))[:8]
        mk = "".join(c for c in mid if _keep(c))
        if len(lk) < 3 and len(rk) < 3:
            return None
        pages = list(zip(self.pages, self.kept))
        for (where, raw), (kept, idx) in pages:
            for m in re.finditer(re.escape(lk), kept) if len(lk) >= 3 else []:
                a = m.end()
                b = kept.find(rk, a, a + len(mk) + 40) if rk else a + len(mk)
                if b < 0:
                    continue
                return self._window(where, raw, idx, m.start(), a, b, b + len(rk))
        # garbled text (columns interleaved) rarely survives on both sides:
        # anchor on one side and show what the PDF has next to it
        for side, ctx in (("前文", lk), ("后文", rk)):
            if len(ctx) < 4:
                continue
            for (where, raw), (kept, idx) in pages:
                k = kept.find(ctx)
                if k < 0:
                    continue
                if side == "前文":
                    w = self._window(where, raw, idx, k, k + len(ctx), k + len(ctx) + len(mk),
                                     k + len(ctx) + len(mk) + 8)
                else:
                    a = max(0, k - len(mk))
                    w = self._window(where, raw, idx, max(0, a - 8), a, k, k + len(ctx))
                w["where"] += f"，仅按{side}定位"
                return w
        return None

    def _window(self, where, raw, idx, l0, a, b, r1):
        def r(i):  # kept index -> raw index
            return idx[min(i, len(idx) - 1)] if idx else 0
        hl_a = r(a) if a < len(idx) else len(raw)
        hl_b = r(b - 1) + 1 if b > a else hl_a
        s = max(0, r(l0) - 30)
        e = min(len(raw), (r(r1 - 1) + 1 if r1 > 0 else hl_b) + 30)
        return {"where": self.kind + "，" + where, "text": raw[s:e],
                "hl": [hl_a - s, hl_b - s]}


# ---- per-unit context ----------------------------------------------------

def unit_objects(U: ev.Units) -> dict[tuple, list[tuple[str, str, object]]]:
    """(label, kind, object) for every alarm on every unit, mirroring
    ev.Units._collect so each pooled unit's labels can be checked against
    what evaluate_corpus counted."""
    rep = U.rep
    out: dict[tuple, list] = defaultdict(list)
    for f in rep.findings:
        if f.severity not in {"high", "medium"}:
            continue
        label = f"{f.layer}:{re.sub(r'[0-9]+', 'N', f.title)}"
        if f.anchor:
            units = U.units_at(f.anchor.paragraph_id, f.anchor.start, f.anchor.end)
        else:
            units = [("ref", rid) for rid in f.refs]
        for u in units:
            out[u].append((label, "finding", f))
    for c in rep.ref_checks:
        if c.status in {"not_found", "mismatch"}:
            out[("ref", c.ref_id)].append((f"status:{c.status}", "ref_check", c))
    claims = {c.id for c in rep.claims}
    for sc in rep.support_checks:
        if sc.label == "unsupported" and sc.claim_id in claims:
            out[("claim", sc.claim_id)].append(("label:unsupported", "support_check", sc))
    for v in rep.revisions:
        if v.kind == "typo":
            for u in U.units_at(v.anchor.paragraph_id, v.anchor.start, v.anchor.end):
                out[u].append(("revision:typo", "revision", v))
    return out


def matched_view(rc) -> dict | None:
    if rc is None:
        return None
    m = rc.matched or {}
    return {"status": rc.status, "issues": rc.issues,
            "title": m.get("title"), "authors": m.get("authors"),
            "year": m.get("year"), "venue": m.get("venue"),
            "doi": m.get("doi"), "url": m.get("url"),
            "pdf_url": m.get("pdf_url"), "source": m.get("source"),
            "abstract": (m.get("abstract") or "")[:EXCERPT_MAX] or None}


def ref_links(ref, rc) -> list[dict]:
    links = []
    m = (rc.matched or {}) if rc else {}
    doi = ref.doi or m.get("doi")
    if doi:
        links.append({"label": "DOI", "url": f"https://doi.org/{doi}"})
    for k, name in (("url", "数据库记录"), ("pdf_url", "PDF")):
        if m.get(k) and not (doi and m[k] == f"https://doi.org/{doi}"):
            links.append({"label": name, "url": m[k]})
    q = quote((ref.title or ref.raw)[:200])
    links.append({"label": "Google Scholar", "url": f"https://scholar.google.com/scholar?q={q}"})
    if ref.lang == "zh":
        links.append({"label": "百度学术", "url": f"https://xueshu.baidu.com/s?wd={q}"})
    return links


def para_window(text: str, a: int, b: int, pad: int = 240) -> dict:
    s, e = max(0, a - pad), min(len(text), b + pad)
    return {"text": text[s:e], "hl": [a - s, b - s],
            "cut_left": s > 0, "cut_right": e < len(text)}


def build_item(paper, lang, rep, U, unit, labels, objs, src, lib_root):
    paras = U.paras
    sec = {s.id: s.title for s in rep.sections}
    refs_by_id = {r.id: r for r in rep.references}
    rcs = {c.ref_id: c for c in rep.ref_checks}
    markers = {m.id: m for m in rep.markers}
    claims = {c.id: c for c in rep.claims}

    loc = {"unit": list(unit)}
    ref_ids: list[str] = []

    def add_refs(ids):
        for r in ids:
            if r not in ref_ids and r in refs_by_id:
                ref_ids.append(r)

    claim = None
    if unit[0] == "ref":
        ref = refs_by_id[unit[1]]
        add_refs([ref.id])
        pid = ref.paragraph_id
        sentence = {"text": ref.raw, "hl": [0, 0], "cut_left": False, "cut_right": False}
        para = None
    elif unit[0] == "claim":
        claim = claims[unit[1]]
        pid = claim.paragraph_id
        para = paras[pid]
        a, b = ev._sentence_key(para.text, claim.start, claim.end)
        sentence = {"text": para.text[a:b], "hl": [claim.start - a, claim.end - a],
                    "cut_left": False, "cut_right": False}
        loc.update(start=claim.start, end=claim.end)
        for mid in claim.marker_ids:
            add_refs(markers[mid].ref_ids if mid in markers else [])
    else:
        pid, a, b = unit[1], unit[2], unit[3]
        para = paras[pid]
        sentence = {"text": para.text[a:b], "hl": [0, 0], "cut_left": False, "cut_right": False}
        loc.update(start=a, end=b)

    alarms, typos, sevs, locs = [], [], [], set()
    for label, kind, o in objs:
        if kind == "finding":
            alarms.append({"label": label, "severity": o.severity, "title": o.title,
                           "detail": o.detail, "id": o.id})
            sevs.append(o.severity)
            add_refs(o.refs)
            if o.anchor:
                if o.anchor.loc:
                    locs.add(o.anchor.loc)
                # refs cited inside the alarm's span (stacking findings carry none)
                for m in rep.markers:
                    if m.paragraph_id == o.anchor.paragraph_id and \
                            ev.overlap((m.start, m.end), (o.anchor.start, o.anchor.end)):
                        add_refs(m.ref_ids)
        elif kind == "ref_check":
            alarms.append({"label": label, "severity": None,
                           "title": f"核验状态 {o.status}", "detail": "；".join(o.issues),
                           "id": o.ref_id})
        elif kind == "support_check":
            alarms.append({"label": label, "severity": "high",
                           "title": "支持度判定 unsupported",
                           "detail": o.rationale, "id": f"{o.claim_id}/{o.ref_id}"})
            sevs.append("high")
        else:
            v = o
            alarms.append({"label": label, "severity": "revision",
                           "title": f"修订「{v.old}」改为「{v.new}」",
                           "detail": v.reason, "id": v.id})
            sevs.append("revision")
            if v.anchor.loc:
                locs.add(v.anchor.loc)
            vp = paras[v.anchor.paragraph_id]
            t = {"old": v.old, "new": v.new, "reason": v.reason,
                 "docx": para_window(vp.text, v.anchor.start, v.anchor.end, 60)}
            if lang == "en":
                if v.anchor.snippet:
                    t["source"] = {"where": f"LaTeX 源码 {v.anchor.loc or ''}",
                                   "text": v.anchor.snippet,
                                   "hl": list(v.anchor.snippet_hl or (0, 0))}
            elif src is not None:
                t["source"] = src.locate(vp.text[max(0, v.anchor.start - 30):v.anchor.start],
                                         v.old, vp.text[v.anchor.end:v.anchor.end + 30])
                if t["source"] is None:
                    t["source_missing"] = f"未能在{src.kind}中定位这段文字"
            typos.append(t)

    # paragraph context around the unit
    context = None
    if para is not None:
        a, b = (loc.get("start", 0), loc.get("end", 0))
        context = para_window(para.text, a, b)

    supports = defaultdict(list)
    if claim is not None:
        for sc in rep.support_checks:
            if sc.claim_id == claim.id:
                supports[sc.ref_id].append(sc)
                add_refs([sc.ref_id])

    refs_out = []
    for rid in ref_ids:
        r = refs_by_id[rid]
        rc = rcs.get(rid)
        sc_out = []
        for sc in supports.get(rid, []):
            src_link = None
            if sc.source_file and lib_root:
                p = (ROOT / lib_root / sc.source_file).resolve()
                src_link = {"label": f"本地 PDF {sc.source_file}" +
                            (f" 第 {sc.source_page} 页" if sc.source_page else ""),
                            "url": p.as_uri() + (f"#page={sc.source_page}" if sc.source_page else "")}
            sc_out.append({
                "label": sc.label, "off_topic": sc.off_topic,
                "source_kind": sc.source_kind, "evidence": sc.evidence,
                "rationale": sc.rationale, "source_title": sc.source_title,
                "excerpt": (sc.source_excerpt or "")[:EXCERPT_MAX] or None,
                "evidence_span": list(sc.evidence_span) if sc.evidence_span else None,
                "source_link": src_link})
        refs_out.append({
            "id": rid, "label": r.label or r.key, "raw": r.raw, "lang": r.lang,
            "parsed": {"title": r.title, "authors": r.authors, "year": r.year,
                       "venue": r.venue, "doi": r.doi},
            "check": matched_view(rc), "links": ref_links(r, rc),
            "support": sc_out})

    para_obj = paras.get(pid) if pid else None
    loc.update(paragraph_id=pid,
               section=sec.get(para_obj.section_id) if para_obj else None,
               tex=sorted(locs))
    sev = min(sevs, key=lambda s: SEV_RANK[s]) if sevs else "high"
    key = U.key(unit)
    return {
        "id": hashlib.sha1(f"{paper}|{unit}|{key}".encode()).hexdigest()[:10],
        "paper": paper, "lang": lang,
        "stratum": stratum_of(labels), "labels": labels, "severity": sev,
        "alarms": sorted(alarms, key=lambda x: SEV_RANK.get(x["severity"] or "high", 0)),
        "sentence": sentence, "context": context, "typos": typos,
        "refs": refs_out, "loc": loc,
    }


# ---- pool / sample -------------------------------------------------------

def build_pool(reports: Path):
    pool, meta = [], {}
    for lang, papers in (("zh", ev.PAPERS), ("en", ev.PAPERS_EN)):
        tot = {"tp": 0, "fn": 0, "fp_new": 0, "pre_existing": 0, "tn": 0}
        for paper in papers:
            inj, clean = reports / f"{paper}_injected.json", reports / f"{paper}_clean.json"
            if not inj.exists() or not clean.exists():
                print(f"skip {paper}: reports missing")
                continue
            spec = json.loads((TESTSET / "injections" / f"{paper}.json").read_text())
            rep = ev.load(inj)
            res = ev.score(rep, ev.load(clean), spec)
            for k in tot:
                tot[k] += res["counts"][k]
            U = ev.Units(rep)
            objs = unit_objects(U)
            src = None
            if lang == "zh" and paper in ZH_SOURCE and (TESTSET / ZH_SOURCE[paper]).exists():
                src = SourceText(TESTSET / ZH_SOURCE[paper])
            lib_root = rep.library.folder if rep.library else None
            for entry in res["pre_existing_units"]:
                unit = tuple(entry["unit"])
                got = sorted({lab for lab, _, _ in objs[unit]})
                if got != entry["alarms"]:
                    raise SystemExit(f"{paper} {unit}: alarm labels {got} != "
                                     f"evaluate_corpus {entry['alarms']}")
                pool.append(build_item(paper, lang, rep, U, unit, entry["alarms"],
                                       objs[unit], src, lib_root))
        meta[lang] = tot
    ids = [p["id"] for p in pool]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate item ids in pool")
    return pool, meta


def allocate(N: dict[str, int], n: int, floor: int = FLOOR) -> dict[str, int]:
    """Proportional allocation, at least `floor` per stratum, strata with
    N <= floor taken whole; largest-remainder rounding."""
    alloc = {h: Nh for h, Nh in N.items() if Nh <= floor}
    rest = {h: Nh for h, Nh in N.items() if h not in alloc}
    budget = n - sum(alloc.values())
    while rest:
        tot = sum(rest.values())
        quota = {h: budget * Nh / tot for h, Nh in rest.items()}
        low = [h for h in rest if quota[h] < floor]
        if not low:
            base = {h: int(q) for h, q in quota.items()}
            left = budget - sum(base.values())
            for h in sorted(quota, key=lambda h: (base[h] - quota[h], h))[:left]:
                base[h] += 1
            alloc.update(base)
            break
        for h in low:
            alloc[h] = floor
            budget -= floor
            del rest[h]
    return {h: min(alloc[h], N[h]) for h in N}


def draw_sample(pool, meta):
    out = {"seed": SEED, "floor": FLOOR, "target": TARGET, "langs": {}}
    for lang in ("zh", "en"):
        items = [p for p in pool if p["lang"] == lang]
        if not items:
            continue
        by = defaultdict(list)
        for p in items:
            by[p["stratum"]].append(p["id"])
        order = sorted(by, key=stratum_rank)
        N = {h: len(by[h]) for h in order}
        n = allocate(N, TARGET[lang])
        rng = random.Random(SEED)
        strata = {}
        for h in order:
            strata[h] = {"N": N[h], "n": n[h],
                         "ids": sorted(rng.sample(sorted(by[h]), n[h]))}
        out["langs"][lang] = {**meta[lang], "pool": len(items), "strata": strata}
    return out


# ---- outputs -------------------------------------------------------------

POOL_COLS = ["id", "paper", "lang", "stratum", "categories", "severity",
             "alarm_text", "sentence", "refs", "evidence", "sources",
             "rationale", "location"]


def pool_row(p) -> dict:
    ev_parts, src_parts, rat_parts = [], [], []
    for r in p["refs"]:
        for s in r["support"]:
            if s["evidence"]:
                ev_parts.append(f"[{r['label']}] {s['label']}: {s['evidence']}")
            if s["rationale"]:
                rat_parts.append(f"[{r['label']}] {s['rationale']}")
            if s["source_link"]:
                src_parts.append(s["source_link"]["url"])
        for ln in r["links"]:
            if ln["label"] in {"DOI", "数据库记录"}:
                src_parts.append(ln["url"])
    for a in p["alarms"]:
        if a["label"] in {"status:not_found", "status:mismatch"}:
            rat_parts.append(a["detail"])
    for t in p["typos"]:
        rat_parts.append(t["reason"])
    loc = p["loc"]
    loc_s = f"{loc['unit'][0]} {loc['paragraph_id'] or ''}"
    if "start" in loc:
        loc_s += f" {loc['start']}-{loc['end']}"
    if loc.get("section"):
        loc_s += f" 章节 {loc['section'][:30]}"
    if loc.get("tex"):
        loc_s += " " + " ".join(loc["tex"])
    return {
        "id": p["id"], "paper": p["paper"], "lang": p["lang"], "stratum": p["stratum"],
        "categories": "; ".join(p["labels"]), "severity": p["severity"],
        "alarm_text": " | ".join(f"{a['title']}：{a['detail']}" for a in p["alarms"]),
        "sentence": p["sentence"]["text"],
        "refs": " | ".join(r["raw"] for r in p["refs"]),
        "evidence": " | ".join(ev_parts),
        "sources": " ".join(dict.fromkeys(src_parts)),
        "rationale": " | ".join(rat_parts), "location": loc_s,
    }


def write_html(path: Path, items: list[dict], sample: dict, reports: Path):
    tpl = (HERE / "annotate_template.html").read_text(encoding="utf-8")
    sid = hashlib.sha1("".join(i["id"] for i in items).encode()).hexdigest()[:8]
    payload = {"audit_id": sid, "reports": str(reports.relative_to(ROOT))
               if reports.is_relative_to(ROOT) else str(reports),
               "strata": {lang: {h: {"N": s["N"], "n": s["n"]} for h, s in d["strata"].items()}
                          for lang, d in sample["langs"].items()},
               "items": items}
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    path.write_text(tpl.replace("/*__DATA__*/null", data), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reports", type=Path, default=TESTSET / "reports")
    ap.add_argument("--out", type=Path, default=HERE)
    args = ap.parse_args()
    reports, out = args.reports.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    pool, meta = build_pool(reports)
    for lang in ("zh", "en"):
        n = sum(1 for p in pool if p["lang"] == lang)
        print(f"{lang}: pool {n}  (evaluate_corpus pre_existing {meta.get(lang, {}).get('pre_existing')})")
        if lang in meta and n != meta[lang]["pre_existing"]:
            raise SystemExit("pool size does not match evaluate_corpus")

    with (out / "pool.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, POOL_COLS)
        w.writeheader()
        for p in pool:
            w.writerow(pool_row(p))

    sample = draw_sample(pool, meta)
    sample["reports"] = str(reports.relative_to(ROOT)) if reports.is_relative_to(ROOT) else str(reports)
    (out / "sample.json").write_text(json.dumps(sample, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8")

    picked = {i for d in sample["langs"].values() for s in d["strata"].values() for i in s["ids"]}
    items = sorted((p for p in pool if p["id"] in picked),
                   key=lambda p: (p["lang"] != "zh", stratum_rank(p["stratum"]), p["paper"], p["id"]))
    write_html(out / "annotate.html", items, sample, reports)

    for lang, d in sample["langs"].items():
        print(f"\n{lang}: {sum(s['n'] for s in d['strata'].values())} sampled of {d['pool']}")
        for h, s in d["strata"].items():
            print(f"  {s['n']:>3} / {s['N']:<3} {h}")
    print(f"\nwrote {out}/pool.csv sample.json annotate.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
