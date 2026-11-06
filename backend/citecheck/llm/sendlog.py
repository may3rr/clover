"""Send list (发送清单): what each cloud request carried.

Every model request — chat, embedding, rerank, cloud or local — is one
``llm_usage`` row. Rows carry the run they belong to, the route, the
characters the request sent (``chars``: every message, instructions
included) and its content ``parts``: each piece of user data with its
category, length, a dedupe key and a truncated copy for display.

Categories:
  claim       cited claim sentences of the manuscript (论断)
  excerpt     excerpts of the cited works (被引片段)
  reference   reference entries and the titles of cited works (参考文献)
  manuscript  other manuscript text: paragraphs, headings, captions,
              title, abstract (稿件正文)
  exemplar    text of venue exemplars and folder PDFs (范文与文献 PDF)
  other       numeric statistics, venue names, database records (其他)

The report summary (``summarize``) is computed from those rows only:
numbers are what was recorded, never estimates.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextvars import ContextVar
from typing import Iterable

log = logging.getLogger(__name__)

CATEGORIES = ("claim", "excerpt", "reference", "manuscript", "exemplar", "other")
CATEGORY_LABELS = {
    "claim": "论断",
    "excerpt": "被引片段",
    "reference": "参考文献",
    "manuscript": "稿件正文",
    "exemplar": "范文与文献 PDF",
    "other": "其他",
}
# what a request carries when the caller names no parts
TASK_CATEGORY = {
    "typo": "manuscript", "function": "manuscript", "profile": "manuscript",
    "extract": "claim", "judge": "claim", "review": "claim",
    "review_fallback": "claim", "structure": "reference", "bibguess": "manuscript",
    "overview": "other", "embed": "excerpt", "rerank": "excerpt",
}
_SHOW = 160         # characters kept per part for display
ITEM_CAP = 80       # distinct items kept per category in a report

Part = tuple[str, str] | tuple[str, str, str]   # (category, text[, key])

current_doc: ContextVar[str | None] = ContextVar("llm_doc", default=None)
current_run: ContextVar[str | None] = ContextVar("llm_run", default=None)


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def pack(parts: Iterable[Part] | None) -> list[dict]:
    """Compact JSON-able parts; empty texts dropped."""
    out: list[dict] = []
    for p in parts or ():
        cat, text = p[0], p[1] or ""
        if not text.strip():
            continue
        key = p[2] if len(p) > 2 and p[2] else text  # type: ignore[misc]
        out.append({"c": cat if cat in CATEGORIES else "other",
                    "n": len(text), "k": _key(key), "t": text[:_SHOW]})
    return out


def message_chars(messages: list[dict]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


def default_parts(task: str, messages: list[dict]) -> list[Part]:
    """The user messages as one part of the task's usual category."""
    text = "\n".join(str(m.get("content") or "") for m in messages
                     if m.get("role") == "user")
    return [(TASK_CATEGORY.get(task, "other"), text)]


def record(cache, *, provider: str, model: str, task: str, route: str,
           prompt: int = 0, completion: int = 0, cached: bool = False,
           chars: int = 0, parts: list[dict] | None = None) -> None:
    """One llm_usage row stamped with the current doc and run. Never
    allowed to break the request path."""
    try:
        cats: dict[str, int] = {}
        for p in parts or []:
            cats[p["c"]] = cats.get(p["c"], 0) + p["n"]
        category = max(cats, key=cats.get) if cats else None
        cache.record_usage(
            provider, model, task, prompt, completion, cached,
            doc=current_doc.get(), run=current_run.get(), route=route,
            chars=chars, category=category,
            parts=json.dumps(parts, ensure_ascii=False) if parts else None)
    except Exception as e:  # noqa: BLE001 — stats must never break calls
        log.debug("usage log write failed: %s", e)


def summarize(rows: list[dict], manuscript_chars: int, *, run: str = "",
              privacy: bool = False, skipped: dict[str, int] | None = None):
    """SendSummary from one run's llm_usage rows (cloud, uncached)."""
    from ..schema import SendCategory, SendItem, SendSummary

    from .privacy import TASK_LABELS

    sent = [r for r in rows if r.get("route") == "cloud" and not r.get("cached")]
    by_cat: dict[str, dict[str, dict]] = {c: {} for c in CATEGORIES}
    content = 0
    for r in sent:
        for p in json.loads(r.get("parts") or "[]"):
            content += p["n"]
            items = by_cat.setdefault(p["c"], {})
            it = items.get(p["k"])
            if it is None:
                items[p["k"]] = {"text": p["t"], "chars": p["n"], "times": 1,
                                 "tasks": [r["task"]]}
            else:
                it["times"] += 1
                if r["task"] not in it["tasks"]:
                    it["tasks"].append(r["task"])
    cats: list[SendCategory] = []
    for c in CATEGORIES:
        items = list(by_cat.get(c, {}).values())
        if not items:
            continue
        cats.append(SendCategory(
            category=c, label=CATEGORY_LABELS[c], count=len(items),
            chars=sum(i["chars"] for i in items),
            items=[SendItem(text=i["text"], chars=i["chars"], times=i["times"],
                            tasks=[TASK_LABELS.get(t, t) for t in i["tasks"]])
                   for i in items[:ITEM_CAP]],
            truncated=max(len(items) - ITEM_CAP, 0)))
    from_ms = sum(x.chars for x in cats if x.category in ("claim", "manuscript"))
    return SendSummary(
        run=run,
        privacy=privacy,
        manuscript_chars=manuscript_chars,
        requests=len(sent),
        cached_requests=sum(1 for r in rows if r.get("cached")),
        local_requests=sum(1 for r in rows
                           if r.get("route") == "local" and not r.get("cached")),
        sent_chars=sum(int(r.get("chars") or 0) for r in sent),
        content_chars=content,
        manuscript_sent_chars=from_ms,
        categories=cats,
        skipped=[{"task": t, "label": TASK_LABELS.get(t, t), "count": n}
                 for t, n in sorted((skipped or {}).items())],
    )
