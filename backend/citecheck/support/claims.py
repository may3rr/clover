"""论断抽取：segment sentences, tag markers inline as ⟦mN⟧, ask the
extract model which span each marker supports.

Claim ``text`` must be a verbatim substring of the sentence (checked
after §5.3 normalization against the sentence with marker text removed);
otherwise the claim falls back to the whole sentence. Claim start/end
are paragraph offsets and exclude the marker text itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel

from ..llm.client import chat_json
from ..schema import CitationMarker, Claim, Paragraph
from .evidence import normalize

# abbreviations/initials/decimals that must not end a sentence
_ABBREV_RE = re.compile(
    r"(?:et al|e\.g|i\.e|cf|Fig|fig|vs|Dr|Mr|Ms|Mrs|No|Nos|Prof|approx|"
    r"Inc|Ltd|Jr|Sr|vol|pp|Eq|Eqs|Sec|Chap|eds|al)\.$"
)
_INITIAL_RE = re.compile(r"(?:^|[\s,;(（])[A-Z]$")
_BOUNDARY = re.compile(r"[.!?;。！？；]|[.!?;。！？；]['\"”’》）\]】]+")


@dataclass
class Sentence:
    start: int
    end: int
    text: str


def split_sentences(text: str) -> list[Sentence]:
    """zh+en sentence segmentation preserving original offsets."""
    out: list[Sentence] = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        m = _BOUNDARY.match(text, i)
        if not m:
            i += 1
            continue
        ch = m.group(0)
        punct_end = m.end()
        if ch[0] == ".":
            prev = text[start:i + 1]
            # decimal point
            if i > 0 and i + 1 < n and text[i - 1].isdigit() and text[i + 1].isdigit():
                i += 1
                continue
            # abbreviation like "et al." / initials "J."
            if _ABBREV_RE.search(prev) or _INITIAL_RE.search(text[:i]):
                i += 1
                continue
            # "file.txt" style: '.' followed directly by lowercase
            if punct_end < n and text[punct_end].islower():
                i += 1
                continue
        # boundary accepted; absorb following closing quotes/brackets
        end = punct_end
        out.append(Sentence(start, end, text[start:end]))
        start = end
        # skip whitespace so the next sentence starts at real text
        while start < n and text[start].isspace():
            start += 1
        i = start
    if start < n:
        out.append(Sentence(start, n, text[start:n]))
    return [s for s in out if s.text.strip()]


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> tuple[str, list[int]]:
    """Delete spans; return (new_text, map new_index -> old_index)."""
    keep = [True] * len(text)
    for a, b in spans:
        for i in range(max(0, a), min(len(text), b)):
            keep[i] = False
    idx_map = [i for i, k in enumerate(keep) if k]
    return "".join(text[i] for i in idx_map), idx_map


class _ClaimsOut(BaseModel):
    claims: list[dict] = []


_PROMPT = (
    "你是学术写作分析助手。下面句子中的 ⟦mN⟧ 是引用标记。找出每个引用标记"
    "所支撑的论断片段，输出 JSON：{{\"claims\": [{{\"text\": \"...\", "
    "\"marker_ids\": [\"m3\"]}}]}}。规则：text 必须是句子的原文连续片段，"
    "不包含 ⟦⟧ 标记本身；找不到对应论断就不要输出；只输出 JSON。\n\n"
    "句子：{sentence}"
)


async def extract_claims(
    paragraph: Paragraph, markers: list[CitationMarker]
) -> list[Claim]:
    """Claims for one paragraph. markers must be pre-filtered to this
    paragraph and sorted by start."""
    if not markers:
        return []
    claims: list[Claim] = []
    sentences = split_sentences(paragraph.text)
    for sent in sentences:
        in_sent = [m for m in markers if m.start >= sent.start and m.end <= sent.end]
        if not in_sent:
            continue
        # build the tagged sentence the model sees
        tagged_parts: list[str] = []
        cursor = sent.start
        for m in in_sent:
            tagged_parts.append(paragraph.text[cursor : m.start])
            tagged_parts.append(f"⟦{m.id}⟧")
            cursor = m.end
        tagged_parts.append(paragraph.text[cursor : sent.end])
        tagged = "".join(tagged_parts)

        res = await chat_json(
            "extract",
            [{"role": "user", "content": _PROMPT.format(sentence=tagged)}],
            _ClaimsOut,
        )

        # verifiable space = sentence text with marker spans removed
        marker_spans = [(m.start - sent.start, m.end - sent.start) for m in in_sent]
        verifiable, idx_map = _remove_spans(sent.text, marker_spans)
        n_verifiable, vmap = normalize(verifiable)

        def locate(claim_text: str) -> tuple[int, int] | None:
            n_claim, _ = normalize(claim_text)
            if not n_claim:
                return None
            pos = n_verifiable.find(n_claim)
            if pos < 0:
                return None
            v_start = idx_map[vmap[pos]]
            v_end = idx_map[vmap[pos + len(n_claim) - 1]] + 1
            return sent.start + v_start, sent.start + v_end

        produced: list[dict] = []
        if res.value is not None:
            produced = [
                c for c in res.value.claims
                if isinstance(c, dict) and c.get("text") and c.get("marker_ids")
            ]
        if not produced:
            produced = [{"text": sent.text.strip(), "marker_ids": [m.id for m in in_sent]}]

        for c in produced:
            span = locate(str(c["text"]))
            if span is None:
                # non-substring output: fall back to the whole sentence
                span = (sent.start, sent.end)
                claim_text = sent.text
            else:
                claim_text = str(c["text"])
            # exclude marker text that sits at the claim's tail (allowing
            # only whitespace / sentence-final punctuation after it)
            end = span[1]
            changed = True
            while changed:
                changed = False
                for m in in_sent:
                    tail = paragraph.text[m.end : end]
                    if m.start < end and not tail.strip(" \t\n。.!！?？,，;；"):
                        end = m.start
                        changed = True
            while end > span[0] and paragraph.text[end - 1].isspace():
                end -= 1
            claims.append(
                Claim(
                    id="", paragraph_id=paragraph.id,
                    start=span[0], end=end,
                    text=paragraph.text[span[0]:end].strip() or claim_text,
                    marker_ids=[str(x) for x in c["marker_ids"]],
                )
            )
    return claims
