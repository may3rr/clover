"""Put a finished report JSON into the local reports table (home-screen history).

    python scripts/import_report.py <report.json> <source.docx> [--id ID]

For the finals machine: a report already run elsewhere opens from the history
list without re-running the pipeline, so a demo shows exactly that result.
The source docx is parsed once so its figure bundle exists locally (the bundle
id is the file's content hash, so it matches the report), and its path is
stored so 导出到 Word works.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from citecheck.cache import Cache
from citecheck.config import get_settings
from citecheck.parse.parser import parse_docx
from citecheck.schema import Report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("source")
    ap.add_argument("--id", default=None)
    a = ap.parse_args()

    src = Path(a.source).resolve()
    rep = Report.model_validate(json.loads(Path(a.report).read_text(encoding="utf-8")))
    parsed = parse_docx(src)
    if parsed.document.assets != rep.document.assets:
        raise SystemExit(f"{src.name} is not the file this report was made from "
                         f"(bundle {parsed.document.assets} vs {rep.document.assets})")
    counts = {"high": 0, "medium": 0, "low": 0}
    for f in rep.findings:
        if f.severity in counts:
            counts[f.severity] += 1
    rid = a.id or f"imported-{rep.document.assets}"
    path = get_settings().cache_path
    Cache(path).save_report(
        rid, rep.document.filename or src.name,
        (rep.document.title or "").strip() or src.stem, str(src), "",
        counts, json.dumps(rep.model_dump(mode="json"), ensure_ascii=False))
    print(f"{rid}  {rep.document.title}  findings {len(rep.findings)} {counts}  -> {path}")


if __name__ == "__main__":
    main()
