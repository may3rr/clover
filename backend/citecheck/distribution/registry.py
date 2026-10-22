"""中文期刊登记表：benchmarks/venues/<id>.toml（投稿规则、别名、识别特征）
加可选的 <id>.json（内置基线，只含统计量）。

Target journal, first match wins:
1. the user's choice;
2. the journal most uncited PDFs in the reference folder come from;
3. traces in the manuscript itself (the journal template's DOI prefix,
   ISSN or CN number, or its name in the front matter).

Baseline, first available wins: the folder's exemplars (>= 5), the
built-in baseline for that journal, else the default English benchmark
(shares only, flagged as not comparable).
"""

from __future__ import annotations

import json
import tomllib
from functools import lru_cache
from pathlib import Path

from ..library.text import squash
from ..parse.parser import ParsedDocument

VENUE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "venues"


@lru_cache(maxsize=1)
def load_venues() -> tuple[dict, ...]:
    out = []
    for p in sorted(VENUE_DIR.glob("*.toml")):
        v = tomllib.loads(p.read_text(encoding="utf-8"))
        v.setdefault("id", p.stem)
        v.setdefault("aliases", [])
        v.setdefault("detect", [])
        v.setdefault("rules", {})
        out.append(v)
    return tuple(out)


def find_venue(name: str | None) -> dict | None:
    """Registry entry for a journal name, id or alias (None if unknown)."""
    if not name:
        return None
    key = squash(name)
    for v in load_venues():
        if key in {squash(v["id"]), squash(v["name"]), *(squash(a) for a in v["aliases"])}:
            return v
    return None


def detect_from_manuscript(parsed: ParsedDocument) -> dict | None:
    """Front matter only (before the first body section): a journal
    named in the reference list is cited, not targeted."""
    canon = {s.id: s.canonical for s in parsed.sections}
    front: list[str] = []
    for p in parsed.paragraphs:
        if canon.get(p.section_id, "other") != "other":
            break
        front.append(p.text)
    head = "\n".join(front[:80])
    for v in load_venues():
        if any(d.lower() in head.lower() for d in v["detect"]):
            return v
        if any(len(a) >= 4 and a in head for a in [v["name"], *v["aliases"]]):
            return v
    return None


def builtin_baseline(venue: dict | None) -> dict | None:
    if venue is None:
        return None
    p = VENUE_DIR / f"{venue['id']}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
