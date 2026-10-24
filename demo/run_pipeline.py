"""Run the real citecheck pipeline on a docx and dump report JSON.

Usage:  python demo/run_pipeline.py <in.docx> <out.json>
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from citecheck.pipeline import run_pipeline


async def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    library = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    def emit(ev: dict) -> None:
        if ev["type"] == "layer":
            print(f"  [{ev['layer']}] {ev['status']}"
                  + (f" findings={ev['findings']}" if "findings" in ev else ""))
        else:
            print(f"  {ev['type']}")

    report = await run_pipeline(src, library_dir=library)
    out.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False,
                   indent=2) + "\n", encoding="utf-8")
    sev = {"high": 0, "medium": 0, "low": 0}
    for f in report.findings:
        sev[f.severity] += 1
    print(f"\n{out}  duration={report.meta.duration_s}s "
          f"findings={sev}  revisions={len(report.revisions)}")
    print("layers:", {k: v.status for k, v in report.meta.layers.items()})
    for f in report.findings:
        print(f"  [{f.severity:6}] {f.layer:12} {f.id:5} {f.title}")


if __name__ == "__main__":
    asyncio.run(main())
