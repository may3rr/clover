"""Time a full pipeline run; prints meta.timings + status counts.

    CITECHECK_CACHE=/tmp/cc_cold.sqlite python scripts/timeit.py [docx]
"""

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citecheck.pipeline import run_pipeline


async def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                Path(__file__).parent.parent / "tests/fixtures/numeric_en.docx")
    events: list[str] = []
    report = await run_pipeline(path, emit=lambda e: events.append(e["type"]))
    counts = Counter(c.status for c in report.ref_checks)
    print("events:", events)
    print("statuses:", dict(counts))
    print("findings:", len(report.findings),
          Counter(f.layer for f in report.findings))
    print("duration_s:", report.meta.duration_s)
    print("timings:", json.dumps(report.meta.timings, indent=1))


asyncio.run(main())
