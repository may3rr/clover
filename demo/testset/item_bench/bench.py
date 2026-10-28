"""Per-item support benchmark: every cited claim is a sample.

Built from the clean reports in demo/testset/reports/. Each base item is one
(claim, cited reference) pair whose reference has a local PDF: linked in the
report's library, or downloaded by fetch_refs.py (library_manifest.json).
Three variants per pair:

  orig   the claim and reference as written. A finding here is an alarm on
         an unmodified citation (an upper bound on false alarms).
  swap   the citation number slips to the nearest reference that has a
         local PDF and is not already cited in the same sentence. Expect a
         finding (unsupported / partial / off_topic).
  alter  one minimal factual edit to the claim, made by the model against
         the evidence a previous run found (only for orig pairs that run
         judged supported). Expect a finding.

The source is built the way the pipeline builds it for a linked PDF
(local_source), so a context change in the product code shows up here
directly. Judging goes through evaluate_with_excerpt, the same cascade and
§5.3 evidence check as a real run.

Usage (from the repo root, conda env claude):
    python demo/testset/item_bench/bench.py build            # orig + swap -> items.json
    python demo/testset/item_bench/bench.py run NAME         # runs/NAME.jsonl
    python demo/testset/item_bench/bench.py alter NAME       # alter items from run NAME
    python demo/testset/item_bench/bench.py report NAME [NAME ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTSET = HERE.parent
ROOT = TESTSET.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))

from pydantic import BaseModel  # noqa: E402

from citecheck.cache import Cache  # noqa: E402
from citecheck.config import get_settings  # noqa: E402
from citecheck.llm.client import chat_json  # noqa: E402
from citecheck.schema import Claim, Reference  # noqa: E402

REPORTS = TESTSET / "reports"
ITEMS = HERE / "items.json"
RUNS = HERE / "runs"
MANIFEST = HERE / "library_manifest.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _papers() -> list[tuple[str, dict]]:
    return [(p.name.removesuffix("_clean.json"), _load(p))
            for p in sorted(REPORTS.glob("*_clean.json"))]


# ---------------------------------------------------------------- build

class _Alter(BaseModel):
    altered: str
    change: str = ""


_ALTER_PROMPT = (
    "下面是一条学术论断，以及被引文献中支持它的原文证据。请对论断做一处最小的"
    "实质改动，使改动后的论断不再被这段证据支持。可以改数字、反转比较或效果的"
    "方向、把方法/数据集/任务/对象换成同领域的另一个、改变适用范围。\n"
    "要求：保持原语言和句式，只改动必要的几个词；改动后读起来仍然通顺可信，"
    "不要只是加一个“不”字；不要改动与证据无关的部分。\n"
    "论断：{claim}\n证据：{evidence}\n\n"
    "输出 JSON：{{\"altered\": \"改动后的论断\", \"change\": \"一句话说明改了什么\"}}。"
    "只输出 JSON。"
)


async def _alter(claim: str, evidence: str) -> _Alter | None:
    res = await chat_json(
        "review",
        [{"role": "user", "content": _ALTER_PROMPT.format(claim=claim, evidence=evidence)}],
        _Alter,
    )
    out = res.value
    if out is None or not out.altered.strip() or out.altered.strip() == claim.strip():
        return None
    if not 0.5 <= len(out.altered) / max(len(claim), 1) <= 1.8:
        return None
    return out


def _local_refs(paper: str, rep: dict) -> dict[str, str]:
    """ref_id -> PDF file name in the paper's library folder."""
    out = dict(json.loads(MANIFEST.read_text("utf-8")).get(paper, {})) if MANIFEST.exists() else {}
    lib = rep.get("library")
    if lib:
        names = {d["id"]: d["filename"] for d in lib["docs"]}
        for link in lib["links"]:
            if link.get("status") != "rejected" and link["doc_id"] in names:
                out[link["ref_id"]] = names[link["doc_id"]]
    return out


def build() -> None:
    items: list[dict] = []
    for paper, rep in _papers():
        local = _local_refs(paper, rep)
        if not local:
            continue
        lang = "en" if paper.startswith("en_") else "zh"
        claims = {c["id"]: c for c in rep["claims"]}
        pos = {r["id"]: i for i, r in enumerate(rep["references"])}
        markers = {m["id"]: m for m in rep["markers"]}
        for sc in rep["support_checks"]:
            if sc["ref_id"] not in local:
                continue
            c = claims[sc["claim_id"]]
            # every ref cited in this sentence stays off-limits for the swap
            same = {rid for mid in c["marker_ids"] for rid in markers[mid]["ref_ids"]}
            same |= {o["ref_id"] for o in rep["support_checks"] if o["claim_id"] == c["id"]}
            here = pos.get(sc["ref_id"], 0)
            cands = sorted((r for r in local if r not in same and r in pos),
                           key=lambda r: (abs(pos[r] - here), pos[r]))
            base = {
                "paper": paper, "lang": lang, "claim_id": c["id"],
                "paragraph_id": c["paragraph_id"], "claim": c["text"],
                "sentence": c.get("sentence"), "ref_id": sc["ref_id"],
                "clean_label": sc["label"], "clean_kind": sc["source_kind"],
            }
            key = f"{paper}:{c['id']}:{sc['ref_id']}"
            items.append({**base, "id": f"{key}:orig", "kind": "orig"})
            if cands:
                items.append({**base, "id": f"{key}:swap", "kind": "swap",
                              "ref_id": cands[0], "orig_ref_id": sc["ref_id"]})
    ITEMS.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(items)} items: {dict(Counter(i['kind'] for i in items))}")


async def make_alter(run_name: str) -> None:
    """Alter items for every orig pair that run judged supported."""
    items = _load(ITEMS)
    items = [i for i in items if i["kind"] != "alter"]
    rows = _rows(run_name)
    bases = [i for i in items if i["kind"] == "orig"
             and rows.get(i["id"], {}).get("label") == "supported"
             and rows[i["id"]].get("evidence")]
    outs = await asyncio.gather(*(_alter(b["claim"], rows[b["id"]]["evidence"]) for b in bases))
    for base, out in zip(bases, outs):
        if out is None:
            continue
        sent = base["sentence"]
        sent = sent.replace(base["claim"], out.altered) if sent and base["claim"] in sent else out.altered
        items.append({**base, "id": base["id"].removesuffix(":orig") + ":alter", "kind": "alter",
                      "claim": out.altered, "sentence": sent, "orig_claim": base["claim"],
                      "change": out.change, "base_evidence": rows[base["id"]]["evidence"]})
    ITEMS.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{sum(o is not None for o in outs)}/{len(bases)} alter items added")


# ---------------------------------------------------------------- run

class _Sources:
    """LocalPdf per (paper, ref_id), scanned once per library folder."""

    def __init__(self, cache: Cache, papers: set[str]):
        from citecheck.library.scan import scan_folder

        self.local: dict[tuple[str, str], object] = {}
        self.refs: dict[tuple[str, str], Reference] = {}
        self.matched: dict[tuple[str, str], dict | None] = {}
        # (paper, claim_id) -> refs cited by that claim, in report order
        self.claim_refs: dict[tuple[str, str], list[str]] = {}
        for paper, rep in _papers():
            if paper not in papers:
                continue
            for sc in rep["support_checks"]:
                self.claim_refs.setdefault((paper, sc["claim_id"]), []).append(sc["ref_id"])
            for r in rep["references"]:
                self.refs[(paper, r["id"])] = Reference.model_validate(r)
            for rc in rep.get("ref_checks", []):
                self.matched[(paper, rc["ref_id"])] = rc.get("matched")
            files = _local_refs(paper, rep)
            folder = (ROOT / rep["library"]["folder"]) if rep.get("library") else None
            if folder is None:
                from fetch_refs import _folder

                folder = _folder(paper)
            by_name = {p.path.name: p for p in scan_folder(folder, cache)}
            for dup in list(by_name.values()):
                for d in dup.doc.duplicates:
                    by_name.setdefault(Path(d).name, dup)
            for rid, name in files.items():
                if name in by_name:
                    self.local[(paper, rid)] = by_name[name]


async def _source(item: dict, src: _Sources):
    from citecheck.library.source import local_source, local_title
    from citecheck.support.sources import SourceText

    key = (item["paper"], item["ref_id"])
    pdf = src.local.get(key)
    if pdf is None:
        return SourceText("none", None, None), None
    from citecheck.support.judge import search_terms

    terms = await search_terms(item["claim"], item.get("sentence"))
    query = " ".join([item["claim"], *terms])
    if FULLTEXT:
        text = await asyncio.to_thread(_fulltext, pdf, query)
        source = SourceText("fulltext" if text else "none", text, pdf.doc.title)
    else:
        source = await asyncio.to_thread(local_source, pdf, query)
    return source, local_title(pdf, src.matched.get(key), src.refs.get(key))


# --fulltext: every pass reads the cited paper's whole body (reference list
# dropped) instead of BM25 windows; bodies past the cap keep their
# best-ranked windows up to the cap
FULLTEXT = False
_FULLTEXT_CAP = 100_000


def _fulltext(pdf, query: str) -> str | None:
    from citecheck.library.source import _drop_reference_tail
    from citecheck.support.sources import _bm25_excerpt

    if not pdf.doc.readable or not pdf.pages:
        return None
    body = _drop_reference_tail(pdf.body()[0]).strip()
    if len(body) <= _FULLTEXT_CAP:
        return body or None
    return _bm25_excerpt(body, query, _FULLTEXT_CAP, head=600, max_parts=1000)


_ENTRY_NUM = re.compile(r"^\s*[\[［]\s*\d+\s*[\]］]")


async def _judge(item: dict, src: _Sources, sem) -> dict:
    from citecheck.library.source import local_expanded
    from citecheck.support.judge import search_terms
    from citecheck.support.layer import evaluate_with_excerpt

    async with sem:
        source, title = await _source(item, src)
        claim = Claim(id=item["claim_id"], paragraph_id=item["paragraph_id"], start=0,
                      end=len(item["claim"]), text=item["claim"], sentence=item["sentence"])
        if source.kind == "none" or not source.excerpt:
            return {"id": item["id"], "label": "undetermined", "off_topic": False,
                    "source_kind": "none", "flag": False, "rationale": "未能获取被引文献原文",
                    "no_source": True}
        ref = src.refs.get((item["paper"], item["ref_id"]))
        # the swap takes the original ref's place; the rest stay co-cited
        own = item.get("orig_ref_id", item["ref_id"])
        cocited = [src.refs[(item["paper"], o)].raw
                   for o in src.claim_refs.get((item["paper"], item["claim_id"]), [])
                   if o not in (own, item["ref_id"]) and (item["paper"], o) in src.refs]
        pdf = src.local.get((item["paper"], item["ref_id"]))
        alternate = None
        if FULLTEXT:
            expand = None  # the first excerpt is already the whole body
        else:
            expand = (lambda q: local_expanded(pdf, q)) if pdf is not None else None
            if pdf is not None and get_settings().support.dual_excerpt:
                from citecheck.library.source import local_source

                terms = await search_terms(item["claim"], item.get("sentence"))
                query = " ".join([item["claim"], *terms])

                def alternate():
                    alt = local_source(pdf, query, dense=False)
                    return alt.excerpt, lambda q: local_expanded(pdf, q, dense=False)
        entry = ref.raw if ref else None
        if entry and "orig_ref_id" in item:
            # a real miscitation shows the sentence's own number in front of
            # the wrong entry: give the swapped entry the original's number
            orig = src.refs.get((item["paper"], item["orig_ref_id"]))
            num = _ENTRY_NUM.match(orig.raw) if orig else None
            entry = _ENTRY_NUM.sub(num.group(0), entry, count=1) if num else entry
        chk = await evaluate_with_excerpt(claim, item["ref_id"], source.excerpt, title, source.kind,
                                          entry=entry,
                                          cocited=cocited or None, expand=expand,
                                          alternate=alternate)
        return {
            "id": item["id"], "label": chk.label, "off_topic": chk.off_topic,
            "source_kind": chk.source_kind, "evidence": chk.evidence,
            "rationale": chk.rationale, "title": title, "excerpt": chk.source_excerpt,
            "flag": chk.label in ("unsupported", "partial") or chk.off_topic,
        }


async def run(name: str, kinds: set[str] | None, concurrency: int,
              ids: set[str] | None = None, model: str | None = None,
              review_model: str | None = None) -> None:
    items = [i for i in _load(ITEMS) if (kinds is None or i["kind"] in kinds)
             and (ids is None or i["id"] in ids)]
    if model:
        # every judging task (first pass, review, fallback) on one model
        models = get_settings().llm.models
        for task in ("judge", "review", "review_fallback"):
            setattr(models, task, model)
    if review_model:
        # the cascade: first pass as configured, escalations on this model
        models = get_settings().llm.models
        for task in ("review", "review_fallback"):
            setattr(models, task, review_model)
    cache = Cache(get_settings().cache_path)
    src = _Sources(cache, {i["paper"] for i in items})
    sem = asyncio.Semaphore(concurrency)
    RUNS.mkdir(exist_ok=True)
    t0 = time.time()
    outs = await asyncio.gather(*(_judge(i, src, sem) for i in items))
    path = RUNS / f"{name}.jsonl"
    # a run may cover some kinds only: keep the other kinds' earlier rows
    prev = _rows(name) if path.exists() else {}
    prev.update({o["id"]: o for o in outs})
    with path.open("w", encoding="utf-8") as fh:
        for o in prev.values():
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    print(f"{len(outs)} items in {time.time() - t0:.0f}s -> {path}")
    report([name])


# ---------------------------------------------------------------- report

def _rows(name: str) -> dict[str, dict]:
    path = RUNS / f"{name}.jsonl"
    # split on "\n" only: splitlines() also breaks on U+2028 and friends,
    # which full-text excerpts carry inside a JSON line
    lines = [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln.strip()]
    return {o["id"]: o for o in map(json.loads, lines)}


def report(names: list[str]) -> None:
    items = {i["id"]: i for i in _load(ITEMS)}
    print("| run | lang | orig alarm | swap detect | alter detect | orig undetermined |")
    print("| --- | --- | --- | --- | --- | --- |")
    for name in names:
        rows = _rows(name)
        for lang in ("en", "zh", "all"):
            stat = defaultdict(lambda: [0, 0])
            und = [0, 0]
            for iid, o in rows.items():
                it = items.get(iid)
                if it is None or o.get("no_source") or (lang != "all" and it["lang"] != lang):
                    continue
                s = stat[it["kind"]]
                s[0] += o["flag"]
                s[1] += 1
                if it["kind"] == "orig":
                    und[0] += o["label"] == "undetermined"
                    und[1] += 1

            def f(k):
                a, n = stat[k]
                return f"{a}/{n} ({a / n:.3f})" if n else "-"
            print(f"| {name} | {lang} | {f('orig')} | {f('swap')} | {f('alter')} | "
                  f"{und[0]}/{und[1]} |")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    r = sub.add_parser("run")
    r.add_argument("name")
    r.add_argument("--kinds", help="comma list of orig,swap,alter (default: all)")
    r.add_argument("--concurrency", type=int, default=32)
    r.add_argument("--ids", type=Path, help="file with one item id per line")
    r.add_argument("--model", help="override the judge/review models, e.g. qwen3.8-max")
    r.add_argument("--review-model", help="override the review models only")
    r.add_argument("--fulltext", action="store_true",
                   help="judge on the cited paper's whole body, not BM25 windows")
    r.add_argument("--dual", action="store_true",
                   help="dual check: keep a flag only when a BM25-only excerpt flags it too")
    a = sub.add_parser("alter")
    a.add_argument("name", help="run whose supported orig verdicts seed the edits")
    p = sub.add_parser("report")
    p.add_argument("names", nargs="+")
    args = ap.parse_args()
    if args.cmd == "build":
        build()
    elif args.cmd == "run":
        global FULLTEXT
        FULLTEXT = args.fulltext
        if args.dual:
            get_settings().support.dual_excerpt = True
        kinds = set(args.kinds.split(",")) if args.kinds else None
        ids = set(args.ids.read_text("utf-8").split()) if args.ids else None
        asyncio.run(run(args.name, kinds, args.concurrency, ids, args.model,
                        args.review_model))
    elif args.cmd == "alter":
        asyncio.run(make_alter(args.name))
    else:
        report(args.names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
