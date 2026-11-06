"""Privacy mode (隐私模式): what may leave the machine.

With ``[privacy] enabled = true``:

- the tasks that read the manuscript's own text (typos, citation
  functions, reference structuring, claim extraction, the venue profile)
  run only on the local model ``[llm.local]``. Without a local model they
  are skipped, never sent to the cloud;
- a cited claim sentence that states the author's own contribution
  ("本文提出", "we propose", "our method") is judged locally only
  (``local_only()``), and is skipped when no local model is available;
- embeddings are computed only by the on-device backend; an API backend
  turns dense retrieval off (BM25 alone). Reranking through an API stays
  allowed for ordinary claims (it receives the cited claim and windows of
  the cited work), never for own-contribution claims.

The cloud then receives only cited claim sentences, excerpts of the cited
works, reference entries and numeric statistics. Off by default.
"""

from __future__ import annotations

import os
import re
from contextvars import ContextVar

from ..config import Settings, get_settings

# tasks whose prompt carries the manuscript's own text
PRIVATE_TASKS: tuple[str, ...] = ("typo", "function", "structure", "extract",
                                  "profile")

TASK_LABELS: dict[str, str] = {
    "typo": "错别字检查",
    "function": "引用功能分类",
    "structure": "参考文献结构化",
    "extract": "论断抽取",
    "profile": "期刊画像",
    "judge": "支持度判断",
    "review": "支持度复核",
    "review_fallback": "支持度复核",
    "overview": "期刊评审",
    "embed": "向量检索",
    "rerank": "重排",
    "own_claim": "作者自身贡献论断的判断",
}


def enabled(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.privacy.enabled) or os.environ.get("CITECHECK_PRIVACY") == "1"


def local_available(settings: Settings | None = None) -> bool:
    """A local model is configured and has not failed to load."""
    s = settings or get_settings()
    if not s.llm.local.enabled:
        return False
    from . import local

    e = local._engine
    return e is None or not e.unavailable_reason


_local_only: ContextVar[bool] = ContextVar("privacy_local_only", default=False)


class local_only:
    """Inside this scope every model call (chat, embedding, rerank) stays
    on this machine or is skipped. Async contextvars keep it per task;
    ``asyncio.to_thread`` carries it into worker threads."""

    def __init__(self, on: bool = True) -> None:
        self.on = on
        self._token = None

    def __enter__(self) -> None:
        self._token = _local_only.set(self.on or _local_only.get())

    def __exit__(self, *exc: object) -> None:
        _local_only.reset(self._token)


def is_local_only() -> bool:
    return _local_only.get()


def allowed_routes(task: str, order: list[str],
                   settings: Settings | None = None) -> list[str]:
    """Filter a route order by privacy mode: private tasks (and anything
    inside ``local_only``) keep the local route only, and only when a
    local model is available. An empty list means: skip, send nothing."""
    s = settings or get_settings()
    private = is_local_only() or (enabled(s) and task in PRIVATE_TASKS)
    if not private:
        return order
    if not local_available(s):
        return []
    return ["local"]


def skipped_tasks(settings: Settings | None = None) -> list[str]:
    """Tasks that privacy mode skips with the current configuration
    (settings page): all private tasks when no local model is available."""
    s = settings or get_settings()
    if local_available(s):
        return []
    return [*PRIVATE_TASKS, "own_claim"]


def dense_allowed(is_local_backend: bool) -> bool:
    """Embeddings: an API backend is off in privacy mode and inside
    ``local_only``."""
    if is_local_backend:
        return True
    return not (enabled() or is_local_only())


def rerank_allowed(is_local_backend: bool) -> bool:
    """Reranking through an API: allowed in privacy mode (the cited claim
    and windows of the cited work), not inside ``local_only``."""
    return is_local_backend or not is_local_only()


# ------------------------------------------------- own-contribution claims

# The author speaking about their own work. Kept narrow on purpose: a
# first-person subject followed by a contribution verb, or "our/本文的"
# followed by an artefact noun. "we follow [3]" or "本文采用 [3] 的方法"
# are ordinary cited claims and stay ordinary.
_ZH_SELF = r"(?:本文|本研究|本章|本节|本课题|我们|笔者)"
_ZH_VERB = (r"(?:首次|进一步|还|也|则|主要|创新性地|在此基础上)?"
            r"(?:提出|设计|构建|建立|开发|研发|实现|改进|扩展|发现|证明|"
            r"验证|贡献|创建|发布|搭建)")
_ZH_NOUN = (r"(?:所提|提出|设计|构建)?的?(?:方法|模型|框架|算法|系统|数据集|"
            r"方案|策略|工作|贡献|创新点)")
_EN_SELF = (r"(?:we|this (?:paper|work|study|article|thesis)|"
            r"in this (?:paper|work|study),? we|our (?:work|study|paper))")
_EN_VERB = (r"(?:(?:first|further|also|then|newly)\s+)?"
            r"(?:propose[sd]?|present(?:s|ed)?|introduce[sd]?|design(?:s|ed)?|"
            r"develop(?:s|ed)?|build|built|construct(?:s|ed)?|extend(?:s|ed)?|"
            r"improve[sd]?|contribute[sd]?|release[sd]?|create[sd]?)")
_EN_NOUN = (r"our\s+(?:proposed\s+|new\s+|novel\s+)?"
            r"(?:methods?|models?|approach(?:es)?|framework|system|algorithms?|"
            r"datasets?|contributions?)")

_OWN = [
    re.compile(_ZH_SELF + _ZH_VERB),
    re.compile(_ZH_SELF + _ZH_NOUN),
    re.compile(r"\b" + _EN_SELF + r"\s+" + _EN_VERB + r"\b", re.I),
    re.compile(r"\b" + _EN_NOUN + r"\b", re.I),
]


def own_contribution(text: str | None) -> bool:
    """True when the sentence states the author's own contribution."""
    if not text:
        return False
    flat = re.sub(r"\s+", " ", text)
    return any(p.search(flat) for p in _OWN)
