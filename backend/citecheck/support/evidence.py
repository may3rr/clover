"""证据逐字校验 (AGENTS §5.3) — non-negotiable.

The model's ``evidence`` must appear verbatim in the cited source text.
Both sides are normalized (Unicode NFKC, whitespace collapsed, quotes
unified) before substring matching; an offset map keeps the located span
in ORIGINAL excerpt coordinates for ``evidence_span``.
"""

from __future__ import annotations

import unicodedata

_QUOTE_MAP = {
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "″": '"',
    "‘": "'", "’": "'", "‚": "'", "′": "'",
}


def normalize(text: str) -> tuple[str, list[int]]:
    """Return (normalized_text, offset_map) where offset_map[i] is the
    index in the ORIGINAL text of the character produced at normalized
    position i."""
    out: list[str] = []
    mapping: list[int] = []
    pending_space = False
    pending_start = 0
    for i, ch in enumerate(text):
        ch = unicodedata.normalize("NFKC", ch)
        # NFKC may expand one char into several (e.g. ［ -> [)
        if len(ch) > 1:
            for c in ch:
                if c.isspace():
                    if out and not pending_space:
                        pending_space, pending_start = True, i
                    continue
                c = _QUOTE_MAP.get(c, c)
                if pending_space and out:
                    out.append(" ")
                    mapping.append(pending_start)
                    pending_space = False
                out.append(c)
                mapping.append(i)
            continue
        if ch.isspace():
            if out and not pending_space:
                pending_space, pending_start = True, i
            continue
        ch = _QUOTE_MAP.get(ch, ch)
        if pending_space and out:
            out.append(" ")
            mapping.append(pending_start)
            pending_space = False
        out.append(ch)
        mapping.append(i)
    return "".join(out), mapping


def normalize_text(text: str) -> str:
    return normalize(text)[0]


def locate_evidence(evidence: str | None, excerpt: str | None) -> tuple[int, int] | None:
    """Find ``evidence`` verbatim (post-normalization) inside ``excerpt``.

    Returns (start, end) in ORIGINAL excerpt coordinates, or None.
    """
    if not evidence or not excerpt or not evidence.strip():
        return None
    n_src, src_map = normalize(excerpt)
    n_ev, _ = normalize(evidence)
    if not n_ev:
        return None
    idx = n_src.find(n_ev)
    if idx < 0:
        return None
    start = src_map[idx]
    end = src_map[idx + len(n_ev) - 1] + 1
    return start, end
