"""Export the Report JSON Schema to backend/schema/report.schema.json.

The frontend generates its TypeScript types from this file; run this
script whenever citecheck/schema.py changes.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citecheck.schema import Report

OUT = Path(__file__).resolve().parent.parent / "schema" / "report.schema.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(
    json.dumps(Report.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"wrote {OUT}")
