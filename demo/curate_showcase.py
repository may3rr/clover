"""Landing-page data from real pipeline runs.

Inputs (raw pipeline output, committed as-is):
  demo/showcase_paper.docx      long_errors.docx + 3 typos (build_showcase.py)
  demo/showcase_report.json     run_pipeline(..., venue_id="emnlp")
  demo/showcase_events.json     the SSE events of that run, with timestamps
  demo/demo_report_v2.json      demo_paper.docx, same pipeline version

The landing page shows the product at full strength, so two kinds of
finding are left out of what it displays: "暂时无法核验" (a source was
rate-limited during the run) and "未能获取这篇文献的原文" (no open full
text). Nothing is added or rewritten; every remaining finding, check,
claim and revision is the pipeline's own output.

  python demo/curate_showcase.py
    -> app/site/public/data/showcase.json, grounded.json, showcase_outline.json
    -> app/site/public/samples/clover-sample.docx  (real export)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "backend"))

from citecheck.export import export_report  # noqa: E402
from citecheck.schema import Report  # noqa: E402

OUT = ROOT / "app" / "site" / "public"
DROP_TITLES = {
    "暂时无法核验这篇文献",
    "未能获取这篇文献的原文，相关论断无法判断",
}
COMMENT_AUTHOR = ("李明", "LM")


def curate(rep: dict, keep_overview: bool, filename: str) -> dict:
    # display name in the replica's history and properties
    rep["document"]["filename"] = filename
    rep["findings"] = [f for f in rep["findings"] if f["title"] not in DROP_TITLES]
    counts: dict[str, int] = {}
    for f in rep["findings"]:
        counts[f["layer"]] = counts.get(f["layer"], 0) + 1
    for k, layer in (rep.get("meta", {}).get("layers") or {}).items():
        layer["findings"] = counts.get(k, 0)
    if not keep_overview:
        rep["overview"] = None
    return rep


def dump(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")


def main() -> None:
    show = curate(json.loads((HERE / "showcase_report.json").read_text()), True,
                  "vericite_emnlp.docx")
    dump(show, OUT / "data" / "showcase.json")

    events = json.loads((HERE / "showcase_events.json").read_text())
    outline = next(e["outline"] for e in events if e["type"] == "parsed")
    dump(outline, OUT / "data" / "showcase_outline.json")

    grounded = curate(json.loads((HERE / "demo_report_v2.json").read_text()), False,
                       "grounded_but_wrong.docx")
    dump(grounded, OUT / "data" / "grounded.json")

    out = OUT / "samples" / "clover-sample.docx"
    out.parent.mkdir(parents=True, exist_ok=True)
    export_report(HERE / "showcase_paper.docx", Report.model_validate(show),
                  out, *COMMENT_AUTHOR)
    print(f"{out.relative_to(ROOT)}  {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
