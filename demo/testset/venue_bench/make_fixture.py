"""Screenshot fixture for the F24 screens: app/fixtures/venue.sample.json.

    python demo/testset/venue_bench/make_fixture.py <manuscript.docx> <ref folder>

Runs the confirmation-step scan and the exemplar comparison on a DAKD
manuscript and its reference folder (model reads come from the cache of
eval.py / an earlier run), then keeps what the two shot states need:
the scan for 核对对标范文, and the distribution fields + venue findings
for the detail view. Manuscript anchors are moved onto the sample
report's first section heading, since the shots render that report.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from citecheck.cache import Cache  # noqa: E402
from citecheck.config import get_settings  # noqa: E402
from citecheck.distribution.layer import run_distribution  # noqa: E402
from citecheck.distribution.venue_metrics import prepare_venue  # noqa: E402
from citecheck.library import build_library  # noqa: E402
from citecheck.library.venue_match import paper_type  # noqa: E402
from citecheck.parse import parse_document  # noqa: E402
from citecheck.distribution.venue import from_pdf  # noqa: E402
from citecheck.server import _venue_entry  # noqa: E402

OUT = ROOT / "app" / "fixtures" / "venue.sample.json"
SAMPLE = ROOT / "app" / "fixtures" / "report.sample.json"


VENUE = "数据分析与知识发现"


async def main(paper: str, ref: str) -> None:
    cache = Cache(get_settings().cache_path)
    parsed = parse_document(paper)
    lib, _local, pdfs = await build_library(
        parsed.references, ref, venue=VENUE, cache=cache, use_model=False, guess_venues=False,
        manuscript_type=paper_type(parsed.document.title))
    by = {p.doc.id: p for p in pdfs}
    bench, ctx = await prepare_venue([from_pdf(by[i]) for i in lib.exemplar_ids], lib.venue, parsed,
                                     cache, use_model=True)
    dist, findings = await run_distribution(parsed, bench=bench, venue=lib.venue,
                                            venue_source="exemplars", venue_ctx=ctx)

    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    head = next(s["heading_paragraph_id"] for s in sample["sections"] if s.get("heading_paragraph_id"))
    n = len(next(p["text"] for p in sample["paragraphs"] if p["id"] == head))
    for m in dist.venue_metrics:
        m.anchors = [a.model_copy(update={"paragraph_id": head, "start": 0, "end": n})
                     for a in m.anchors[:3]]
    venue_findings = [f.model_copy(update={"anchor": None, "id": f"venue-{i}"})
                      for i, f in enumerate(x for x in findings if x.metrics
                                                     and not x.metrics[0].startswith(("share:", "density:")))]
    scan = {
        "entry": _venue_entry(lib),
        "paper": "/Users/me/论文/manuscript.docx",
        "paper_type": "research",
        "candidates": [],
        "kind": "docx",
        "library": {**lib.model_dump(mode="json"), "folder": "/Users/me/论文/ref"},
        "references": [
            {"id": r.id, "label": r.label, "title": r.title, "authors": r.authors[:3],
             "year": r.year, "lang": r.lang, "raw": r.raw[:300]}
            for r in parsed.references if r.origin == "list"
        ],
    }
    out = {
        "scan": scan,
        "distribution": {k: v for k, v in dist.model_dump(mode="json").items()
                         if k in {"venue", "venue_source", "n_papers", "benchmark_name",
                                  "exemplars", "venue_metrics"}},
        "findings": [f.model_dump(mode="json") for f in venue_findings],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(dist.venue_metrics)} metrics, {len(venue_findings)} findings")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
