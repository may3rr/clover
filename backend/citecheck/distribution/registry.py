"""期刊与会议登记表：benchmarks/venues/<id>.toml（投稿规则、别名、识别特征、
排除词）加可选的 <id>.json（内置基线，只含统计量）。

The target is whatever the user typed on the home screen (blank = no
benchmarking). The registry only helps to recognise it: a typed name, id
or alias maps to its entry, and ``mentions_venue`` tells whether a
reference's journal or conference string names the same venue. An
unknown name still works, matched by its own spelling.
"""

from __future__ import annotations

import json
import re
import tomllib
from functools import lru_cache
from pathlib import Path

from ..library.text import squash

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
        v.setdefault("exclude", [])
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


def resolve_target(name: str | None) -> tuple[str, dict | None] | None:
    """(display name, registry entry or None) for what the user typed;
    None when blank. A known venue shows its registry name."""
    name = re.sub(r"^[《〈]|[》〉]$", "", (name or "").strip()).strip()
    if not name:
        return None
    entry = find_venue(name)
    return (entry["name"] if entry else name), entry


# a word after the name that makes it another journal ("Pattern
# Recognition Letters"), and the words before "of / on" that do so
# ("International Journal of Pattern Recognition")
_CONT = {"letters", "communications", "reviews", "review", "research", "transactions",
         "magazine", "reports", "express", "advances", "part", "open", "interfaces",
         "applications", "perspectives", "bulletin", "quarterly", "annals", "supplement"}
_HOST = {"journal", "transactions", "annals", "archives", "review", "reviews", "letters"}


def _acronym(n: str) -> bool:
    """ACL, EMNLP: matched as whole words, case-sensitive, never inside
    another acronym (NAACL, EACL)."""
    return bool(re.fullmatch(r"[A-Z]{2,8}", n.strip()))


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def _latin_in(name: str, text: str) -> bool:
    nw, tw = _words(name), _words(text)
    if not nw:
        return False
    for i in range(len(tw) - len(nw) + 1):
        if tw[i:i + len(nw)] != nw:
            continue
        nxt = tw[i + len(nw)] if i + len(nw) < len(tw) else None
        prev = tw[i - 2:i]
        if nxt in _CONT or (len(prev) == 2 and prev[1] in {"of", "on", "for"}
                            and prev[0] in _HOST):
            continue
        return True
    return False


def mentions_venue(text: str | None, name: str, entry: dict | None = None) -> bool:
    """Whether a journal / proceedings string (or a whole reference entry)
    names the target venue by its name or an alias. Chinese names are
    contained after squashing; Latin names as a word sequence that does
    not continue into a longer title; acronyms as whole words. Excluded
    words (Findings, Workshop …) the target itself lacks rule a string
    out."""
    if not text:
        return False
    key = squash(text)
    names = [name, *(([entry["name"], *entry["aliases"]]) if entry else [])]
    target = " ".join(names).lower()
    for x in (entry or {}).get("exclude", []):
        if x.lower() not in target and squash(x) in key:
            return False
    for n in dict.fromkeys(n.strip() for n in names):
        if not squash(n):
            continue
        if squash(n) == key:
            return True
        if _acronym(n):
            if re.search(rf"(?<![A-Za-z]){n}(?![A-Za-z])", text):
                return True
        elif re.search(r"[一-鿿]", n):
            if len(squash(n)) >= 4 and squash(n) in key:
                return True
        elif _latin_in(n, text):
            return True
    return False


def doi_in_venue(doi: str | None, entry: dict | None) -> bool:
    """The DOI carries one of the venue's registered DOI prefixes."""
    if not doi or not entry:
        return False
    return any(d.startswith("10.") and doi.lower().startswith(d.lower())
               for d in entry["detect"])


def builtin_baseline(venue: dict | None) -> dict | None:
    if venue is None:
        return None
    p = VENUE_DIR / f"{venue['id']}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
