"""Rule-level quantity check on a first-pass 'supported' verdict.

The rule never decides a label. It only decides whether a supported
verdict goes on to the review model, and hands the review a neutral note
saying which two numbers differ. The verdict stays the model's (AGENTS.md
§5.2); the review still has to quote located evidence (§5.3).

A quantity is a number plus the token right after it, its unit ("14
times", "5 fps", "63.75 %", "80 类"). A claim quantity and an excerpt
quantity describe the same thing when they share the unit and at least
two content tokens around them ("140 times fewer training steps" against
"14 times fewer training steps"). The rule fires when such a pair differs
and the claim's value can be neither found in the excerpt nor derived from
two excerpt numbers of the same unit by +, -, × or ÷ (a claimed gain of
0.42 between 63.75 and 63.33 is consistent). No unit list and no keyword
list: the same code reads any language whose words the tokenizer splits,
and a claim and excerpt in different languages share no context, so the
rule stays silent there rather than guess.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass

_TOKEN = re.compile(
    r"\d+(?:[.,]\d+)*"              # number
    r"|[^\W\d_]+(?:[-'’][^\W\d_]+)*"  # word (latin or any script with spaces)
    r"|[^\s\w]",                     # a single symbol: % × ( …
    re.UNICODE,
)
_CJK = re.compile(r"[㐀-鿿]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WINDOW = 6
_MIN_SHARED = 2


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str
    surface: str
    context: frozenset[str]


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _tokens(text: str) -> list[str]:
    """Words, numbers and symbols; a run of CJK characters becomes single
    characters, since CJK text has no spaces to split words on."""
    out: list[str] = []
    for t in _TOKEN.findall(text):
        if _CJK.search(t):
            out.extend(t)
        else:
            out.append(t)
    return out


def _value(raw: str) -> float | None:
    # 1,234 is a thousands separator; 3,5 is not read as a decimal comma
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _unit(tok: str) -> str:
    u = tok.casefold()
    return u[:-1] if len(u) > 3 and u.endswith("s") else u


def _context(toks: list[str], lo: int, hi: int) -> frozenset[str]:
    """Content keys in toks[lo:hi]: words of four or more letters (light
    plural folding) and CJK character bigrams."""
    keys: set[str] = set()
    prev_cjk: str | None = None
    for t in toks[lo:hi]:
        if _CJK.fullmatch(t):
            if prev_cjk:
                keys.add(prev_cjk + t)
            prev_cjk = t
            continue
        prev_cjk = None
        if t.isalpha() and len(t) >= 4:
            keys.add(_unit(t))
    return frozenset(keys)


def quantities(text: str) -> list[Quantity]:
    toks = _tokens(_norm(text))
    out: list[Quantity] = []
    for i, t in enumerate(toks):
        if not _NUMBER.fullmatch(t) or i + 1 >= len(toks):
            continue
        unit_tok = toks[i + 1]
        if _NUMBER.fullmatch(unit_tok) or unit_tok in ".,;:，。；：、)]）】":
            continue
        v = _value(t)
        if v is None:
            continue
        ctx = _context(toks, max(0, i - _WINDOW), i) | _context(
            toks, i + 2, i + 2 + _WINDOW)
        out.append(Quantity(v, _unit(unit_tok), f"{t} {unit_tok}".strip(), ctx))
    return out


def _close(a: float, b: float) -> bool:
    """Same number up to rounding (76.2 vs 76.15) or a tiny relative gap."""
    return abs(a - b) <= max(0.051, 0.01 * max(abs(a), abs(b)))


def _derivable(v: float, pool: list[float]) -> bool:
    for a, b in itertools.combinations(pool, 2):
        cands = [a + b, abs(a - b), a * b]
        if a:
            cands.append(b / a)
        if b:
            cands.append(a / b)
        if any(_close(v, c) for c in cands):
            return True
    return False


def number_conflicts(claim: str, excerpt: str) -> list[tuple[str, str]]:
    """(claim surface, excerpt surface) pairs that describe the same
    quantity with different values the excerpt cannot account for."""
    ex_q = quantities(excerpt)
    if not ex_q:
        return []
    all_values = [v for v in (_value(m.group(0)) for m in
                              _NUMBER.finditer(_norm(excerpt))) if v is not None]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for q in quantities(claim):
        if q.surface in seen or any(_close(q.value, v) for v in all_values):
            continue
        same_unit = [p for p in ex_q if p.unit == q.unit]
        match = max(same_unit, key=lambda p: len(p.context & q.context),
                    default=None)
        if match is None or len(match.context & q.context) < _MIN_SHARED:
            continue
        if _close(match.value, q.value):
            continue
        if _derivable(q.value, [p.value for p in same_unit]):
            continue
        seen.add(q.surface)
        out.append((q.surface, match.surface))
    return out


def review_hint(claim: str, excerpt: str) -> str | None:
    """A neutral note for the review pass, or None when nothing differs."""
    pairs = number_conflicts(claim, excerpt)
    if not pairs:
        return None
    return "；".join(
        f"论断中的“{a}”与原文片段中的“{b}”看起来描述同一项数值，但数值不同"
        for a, b in pairs) + "。请核对这一项。"
