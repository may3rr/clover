"""LLM-assisted bibliography boundary — the LAST resort, used only when
every deterministic path (ref heading, ZOTERO_BIBL field, trailing
numbered run) found no reference list.

We send the cheap model a numbered index of the document (paragraph
number + first 80 chars) and ask where the bibliography starts. The
answer is NEVER trusted: the claimed span is accepted only if it
deterministically parses as references — at least 3 non-empty
paragraphs carrying a (19|20)xx year token. Anything else returns None
and the document reports its citation-free state honestly.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from ..llm.client import chat_json
from ..refs.structure import parse_reference
from .parser import ParsedDocument

log = logging.getLogger(__name__)

_MAX_PARAS = 400  # window over the document tail; bibliographies sit there
_MIN_ENTRIES = 3
_YEAR = re.compile(r"(19|20)\d{2}")

_PROMPT = """\
下面是文档按段落编号的摘要（每行：序号 + 该段开头）。这是一篇论文，
但没有检测到"参考文献/References"标题。参考文献列表通常位于文末。
请判断哪一段是参考文献列表的第一条，只输出 JSON：
{{"start": <段落序号>}}；如果全文没有参考文献列表，输出 {{"start": null}}。

{index}"""


class _BibOut(BaseModel):
    start: int | None = None


def _verifies(paragraphs: list, start: int) -> bool:
    """Deterministic check on the claimed span [start, end):
    - the paragraph AT ``start`` is itself a reference (year token);
    - >= _MIN_ENTRIES non-empty paragraphs carry a year-like token;
    - year-bearing entries are >= 60% of the span's non-empty paragraphs.
    """
    n = len(paragraphs)
    if start < 0 or start >= n:
        return False
    first = paragraphs[start].text.strip()
    if not (first and _YEAR.search(first)
            and parse_reference(first)["year"]):
        return False
    hits = 0
    nonempty = 0
    for p in paragraphs[start:]:
        t = p.text.strip()
        if not t:
            continue
        nonempty += 1
        if _YEAR.search(t) and parse_reference(t)["year"]:
            hits += 1
    if hits < _MIN_ENTRIES:
        return False
    return nonempty > 0 and hits * 5 >= nonempty * 3


async def guess_bibliography_start(parsed: ParsedDocument) -> int | None:
    """Index into parsed.paragraphs where the bibliography begins, or
    None when the model has no answer / the answer fails verification."""
    paras = parsed.paragraphs
    offset = 0
    window = paras
    if len(paras) > _MAX_PARAS:
        offset = len(paras) - _MAX_PARAS
        window = paras[offset:]
    index = "\n".join(
        f"{i}: {p.text[:80]}" for i, p in enumerate(window, start=offset)
        if p.text.strip())
    if not index:
        return None
    res = await chat_json(
        "extract",
        [{"role": "user", "content": _PROMPT.format(index=index)}],
        _BibOut,
    )
    if res.value is None or res.value.start is None:
        return None
    start = res.value.start
    if _verifies(paras, start):
        log.info("llm bibliography boundary accepted at paragraph %d", start)
        return start
    log.info("llm bibliography boundary %d rejected by verification", start)
    return None
