"""Dump the full pool items (with text keys) as JSON for labelling."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
TESTSET = HERE.parent.parent
sys.path.insert(0, str(TESTSET / "precision_audit"))
sys.path.insert(0, str(TESTSET))
import build_pool as bp
import evaluate_corpus as ev

reports = TESTSET / "reports"
pool, meta = bp.build_pool(reports)
# attach text keys
keys = {}
for lang, papers in (("zh", ev.PAPERS), ("en", ev.PAPERS_EN)):
    for paper in papers:
        rep = ev.load(reports / f"{paper}_injected.json")
        U = ev.Units(rep)
        for p in pool:
            if p["paper"] == paper:
                p["text_key"] = U.key(tuple(p["loc"]["unit"]))
out = HERE.parent / "pool" / "items.json"
out.write_text(json.dumps(pool, ensure_ascii=False, indent=1, default=str))
print(len(pool), out)
