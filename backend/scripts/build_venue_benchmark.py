"""Build a built-in Chinese journal baseline from a folder of its papers.

    python scripts/build_venue_benchmark.py dakd "/path/to/数据分析与知识发现 ref"

Only PDFs whose CNKI cover / 引用本文 names the journal are used. The
output (benchmarks/venues/<id>.json) holds statistics only — no titles,
no text — so it can ship with the app.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citecheck.distribution.registry import VENUE_DIR, find_venue
from citecheck.distribution.venue import build_venue_benchmark
from citecheck.library.scan import scan_folder


def main() -> None:
    venue_id, folder = sys.argv[1], sys.argv[2]
    venue = find_venue(venue_id)
    if venue is None:
        sys.exit(f"unknown venue {venue_id}: add benchmarks/venues/{venue_id}.toml first")
    pdfs = [p for p in scan_folder(folder) if find_venue(p.doc.venue) is venue]
    bench = build_venue_benchmark(pdfs, venue["name"])
    if bench is None:
        sys.exit(f"too few readable papers of {venue['name']} in {folder}")
    bench["id"] = venue["id"]
    bench["name"] = f"《{venue['name']}》"
    bench["built_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = VENUE_DIR / f"{venue['id']}.json"
    out.write_text(json.dumps(bench, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({bench['n_papers']} papers)")


if __name__ == "__main__":
    main()
