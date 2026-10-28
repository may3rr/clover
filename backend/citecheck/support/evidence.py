"""证据逐字校验 (AGENTS §5.3) — non-negotiable.

The model's ``evidence`` must appear verbatim in the cited source text.
Both sides are normalized (Unicode NFKC, whitespace collapsed, quotes
unified) before substring matching; an offset map keeps the located span
in ORIGINAL excerpt coordinates for ``evidence_span``. For matching only,
a PDF line-break hyphen between lowercase letters ("classi- fication") is
joined on both sides, since the model copies the word whole.
"""

from __future__ import annotations

import re
import unicodedata

_QUOTE_MAP = {
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "″": '"',
    "‘": "'", "’": "'", "‚": "'", "′": "'",
}


def _cjk(c: str) -> bool:
    return ("\u3000" <= c <= "\u303f" or "\u3400" <= c <= "\u9fff"
            or "\uff00" <= c <= "\uffef")


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
                if pending_space and out and not (_cjk(out[-1]) or _cjk(c)):
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
        # pypdf spaces Chinese glyphs apart ("代 伟"): whitespace next to
        # a CJK character is dropped on both sides of the comparison
        if pending_space and out and not (_cjk(out[-1]) or _cjk(ch)):
            out.append(" ")
            mapping.append(pending_start)
        pending_space = False
        out.append(ch)
        mapping.append(i)
    return "".join(out), mapping


def normalize_text(text: str) -> str:
    return normalize(text)[0]


def _join_hyphens(text: str, mapping: list[int]) -> tuple[str, list[int]]:
    """Drop "- " between two ASCII lowercase letters, keeping the map."""
    out: list[str] = []
    out_map: list[int] = []
    i, n = 0, len(text)
    while i < n:
        if (text[i] == "-" and i + 2 < n and text[i + 1] == " " and out
                and "a" <= out[-1] <= "z" and "a" <= text[i + 2] <= "z"):
            i += 2
            continue
        out.append(text[i])
        out_map.append(mapping[i])
        i += 1
    return "".join(out), out_map


def locate_evidence(evidence: str | None, excerpt: str | None) -> tuple[int, int] | None:
    """Find ``evidence`` verbatim (post-normalization) inside ``excerpt``.

    Returns (start, end) in ORIGINAL excerpt coordinates, or None.
    """
    if not evidence or not excerpt or not evidence.strip():
        return None
    n_src, src_map = _join_hyphens(*normalize(excerpt))
    n_ev, _ = _join_hyphens(*normalize(evidence))
    if not n_ev:
        return None
    idx = n_src.find(n_ev)
    if idx < 0:
        return None
    start = src_map[idx]
    end = src_map[idx + len(n_ev) - 1] + 1
    return start, end


_ELLIPSIS = re.compile(r"\.{3,}|…+|⋯+")


def locate_spliced(
    evidence: str | None, excerpt: str | None
) -> tuple[str, tuple[int, int]] | None:
    """Evidence the model spliced with an ellipsis ("A... B"): every piece
    must be found verbatim, in order, in ``excerpt``; the longest piece is
    then kept as the evidence, so what is shown stays one verbatim span.
    Returns (piece, span) or None."""
    if not evidence or not excerpt:
        return None
    pieces = [p.strip() for p in _ELLIPSIS.split(evidence)]
    pieces = [p for p in pieces if len(p) >= 8]
    if len(pieces) < 2:
        return None
    n_src, src_map = _join_hyphens(*normalize(excerpt))
    pos, found = 0, []
    for p in pieces:
        n_p, _ = _join_hyphens(*normalize(p))
        idx = n_src.find(n_p, pos)
        if not n_p or idx < 0:
            return None
        found.append((len(n_p), p, src_map[idx], src_map[idx + len(n_p) - 1] + 1))
        pos = idx + len(n_p)
    _, piece, start, end = max(found, key=lambda f: f[0])
    return piece, (start, end)
