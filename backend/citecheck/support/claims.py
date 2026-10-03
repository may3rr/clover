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
        # inside an open bracket — "(Lewis et al., 2020; Guu et al., 2020)",
        # "[3; 7]" — punctuation separates citations, not sentences
        seg = text[start:i]
        if (seg.count("(") + seg.count("（") + seg.count("[")
                > seg.count(")") + seg.count("）") + seg.count("]")):
            i += 1
            continue
        if ch[0] == ".":
            prev = text[start:i + 1]
            # decimal point
            if i > 0 and i + 1 < n and text[i - 1].isdigit() and text[i + 1].isdigit():
                i += 1
                continue
            # abbreviation like "et al." / initials "J." — the initial
            # test is $-anchored: only the last 2 chars can match, so
            # don't rescan the whole prefix (O(n^2) on PDF fulltext)
            if _ABBREV_RE.search(prev) or _INITIAL_RE.search(
                text[max(0, i - 2):i]
            ):
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
        in_ids = {m.id for m in in_sent}

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

        def add_fallback(mids: list[str]) -> None:
            """Whole-sentence claim (markers removed) for uncovered ids."""
            if not mids or not idx_map:
                return
            # bound the span to the first/last non-punctuation kept char so
            # tail markers and sentence-final '.' stay outside
            punct = " \t\n。.!！?？,，;；"
            nonpunct = [i for i, c in enumerate(verifiable) if c not in punct]
            if not nonpunct:
                return
            i0, i1 = nonpunct[0], nonpunct[-1]
            f_start = sent.start + idx_map[i0]
            f_end = sent.start + idx_map[i1] + 1
            claims.append(
                Claim(
                    id="", paragraph_id=paragraph.id,
                    start=f_start, end=f_end,
                    text=re.sub(r"\s{2,}", " ", verifiable[i0 : i1 + 1].strip()),
                    marker_ids=mids,
                    sentence=sent.text,
                )
            )

        produced: list[dict] = []
        if res.value is not None:
            for c in res.value.claims:
                if not isinstance(c, dict) or not c.get("text"):
                    continue
                # marker ids are global (m0..mN); keep only ids that are
                # actually in this sentence
                ids = [str(x) for x in c.get("marker_ids") or []
                       if str(x) in in_ids]
                if ids:
                    produced.append({"text": str(c["text"]), "marker_ids": ids})

        covered: set[str] = set()
        fallback_ids: list[str] = []
        for c in produced:
            span = locate(c["text"])
            if span is None or _claim_too_short(c["text"]):
                # non-substring / junk claim: whole sentence, markers removed
                fallback_ids += [i for i in c["marker_ids"] if i not in fallback_ids]
                continue
            claim_text = c["text"]
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
            # claim text shown to the judge is marker-free; the span keeps
            # paragraph coordinates so markers inside stay inside the anchor
            inner = paragraph.text[span[0]:end]
            inner_spans = [
                (m.start - span[0], m.end - span[0])
                for m in in_sent
                if span[0] <= m.start and m.end <= end
            ]
            if inner_spans:
                inner, _ = _remove_spans(inner, inner_spans)
            claims.append(
                Claim(
                    id="", paragraph_id=paragraph.id,
                    start=span[0], end=end,
                    text=re.sub(r"\s{2,}", " ", inner).strip() or claim_text,
                    marker_ids=c["marker_ids"],
                    sentence=sent.text,
                )
            )
            covered.update(c["marker_ids"])
        fallback_ids += [m.id for m in in_sent
                         if m.id not in covered and m.id not in fallback_ids]
        add_fallback(fallback_ids)
    return claims


_CJK_CHAR = re.compile(r"[一-鿿]")
_WORD = re.compile(r"[A-Za-z0-9]+")


def _claim_too_short(text: str) -> bool:
    """Reject fragment claims the small model likes to emit — e.g.
    'Following earlier work' — they carry no checkable proposition."""
    cjk = len(_CJK_CHAR.findall(text))
    words = len(_WORD.findall(text))
    if cjk and cjk >= words:
        return cjk < 8
    return words < 4
