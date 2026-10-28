"""Configuration loading for citecheck.

Reads secrets from backend/.env and tunables from backend/config.toml
(falling back to backend/config.example.toml when config.toml is absent).
The packaged app sets CITECHECK_HOME (~/Library/Application Support/Clover)
so .env and config.toml live in the user's Library, never in the bundle.
Model names, base URLs and temperatures all live in config.toml — code
must not hard-code them (AGENTS.md §5.2).
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_HOME = Path(os.environ["CITECHECK_HOME"]) if os.environ.get("CITECHECK_HOME") \
    else _BACKEND_DIR
_ENV_PATH = _HOME / ".env"
_CONFIG_PATH = _HOME / "config.toml"
_CONFIG_EXAMPLE_PATH = _BACKEND_DIR / "config.example.toml"


def _load_dotenv(path: Path) -> dict[str, str]:
    """Tiny .env parser: KEY=VALUE lines, '#' comments, optional quotes."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key.strip()] = value
    return env


class CloudSettings(BaseModel):
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout: float = 60
    max_concurrency: int = 12


# The settings UI exposes two tiers; each tier fans out to these tasks.
# review_fallback rides the fast tier so a failing deep model still has a
# different model to fall back to.
MODEL_TIERS: dict[str, tuple[str, ...]] = {
    "fast": ("judge", "extract", "typo", "structure", "function",
             "review_fallback", "profile"),
    "deep": ("review", "overview"),
}


class ModelNames(BaseModel):
    judge: str = "qwen3.8-flash"
    review: str = "qwen3.8-max"
    review_fallback: str = "qwen3.7-max"
    extract: str = "qwen3.7-flash"
    typo: str = "qwen3.8-flash"
    structure: str = "qwen3.7-flash"
    function: str = "qwen3.7-flash"
    profile: str = "qwen3.8-flash"   # overview: paper "shape" extraction
    overview: str = "qwen3.8-max"    # overview: venue-level critic


class PriceSettings(BaseModel):
    """RMB per 1M tokens; used to estimate cost in the usage log."""

    input: float = 0.0
    output: float = 0.0


# Bailian list prices (北京地域原价), 2026-10 — override in config.toml.
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "qwen3.8-max": {"input": 12.0, "output": 36.0},
    "qwen3.7-max": {"input": 12.0, "output": 36.0},
    "qwen3.7-plus": {"input": 2.0, "output": 8.0},
    "qwen3.8-flash": {"input": 0.8, "output": 2.7},
    "qwen3.7-flash": {"input": 0.2, "output": 0.8},
    "qwen3.6-flash": {"input": 1.2, "output": 7.2},
    "qwen3.5-flash": {"input": 0.2, "output": 2.0},
    "qwen3.8-27b": {"input": 3.0, "output": 12.0},
    "qwen-plus": {"input": 0.8, "output": 2.0},
}


class LocalSettings(BaseModel):
    enabled: bool = False
    model: str = "mlx-community/Qwen2.5-3B-Instruct-4bit"
    hf_endpoint: str = "https://hf-mirror.com"
    timeout: float = 20


class EmbeddingSettings(BaseModel):
    """Qwen3-Embedding for excerpt retrieval, fused with BM25. Off by
    default: it sends the cited PDFs' text to the embedding service."""

    enabled: bool = False
    base_url: str = "https://api.siliconflow.cn/v1"
    model: str = "Qwen/Qwen3-Embedding-0.6B"
    api_key_env: str = "SILICONFLOW_API_KEY"
    timeout: float = 60
    batch: int = 32
    max_concurrency: int = 4


class RerankSettings(BaseModel):
    """Qwen3-Reranker over the top fused candidates before the excerpt is
    filled. Off by default, for the same reason as embeddings."""

    enabled: bool = False
    base_url: str = "https://api.siliconflow.cn/v1"
    model: str = "Qwen/Qwen3-Reranker-0.6B"
    api_key_env: str = "SILICONFLOW_API_KEY"
    api_format: Literal["siliconflow", "dashscope"] = "siliconflow"
    candidates: int = 40
    timeout: float = 60


class LLMSettings(BaseModel):
    temperature: float = 0
    cloud: CloudSettings = Field(default_factory=CloudSettings)
    models: ModelNames = Field(default_factory=ModelNames)
    local: LocalSettings = Field(default_factory=LocalSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    rerank: RerankSettings = Field(default_factory=RerankSettings)
    prices: dict[str, PriceSettings] = Field(
        default_factory=lambda: {
            k: PriceSettings(**v) for k, v in _DEFAULT_PRICES.items()
        }
    )


class RetrievalSettings(BaseModel):
    # default in-flight requests per source; each source has its own
    # limit so a slow host never queues the others behind it
    concurrency: int = 4
    # per-source overrides, sized to each API's published limits:
    # Crossref polite pool (mailto) ~3 concurrent, OpenAlex 10 req/s,
    # Semantic Scholar 1 req/s without a key
    per_source: dict[str, int] = Field(default_factory=lambda: {
        "crossref": 3, "openalex": 6, "s2": 1, "arxiv": 1})
    timeout: float = 15
    retries: int = 2


class SupportSettings(BaseModel):
    # re-judge every flagged pair on a second, BM25-only excerpt and keep
    # the flag only when both agree (needs embeddings for the excerpts to
    # differ; results.md §14)
    dual_excerpt: bool = False


class VenueSettings(BaseModel):
    # 期刊对标细化：model reads of the exemplars (heading types, research
    # elements, citation functions) and the journal of unplaced PDFs. Off:
    # rule-based statistics only, nothing about the exemplars leaves the Mac
    model: bool = True


class CacheSettings(BaseModel):
    path: str = "~/Library/Application Support/citecheck/cache.sqlite"


class Settings(BaseModel):
    dashscope_api_key: str | None = None
    crossref_mailto: str | None = None
    openalex_api_key: str | None = None
    s2_api_key: str | None = None
    embedding_api_key: str | None = None
    rerank_api_key: str | None = None
    # Bumped into every LLM cache key: change it to invalidate all cached
    # model verdicts after a model upgrade or a prompt fix (retrieval
    # entries expire on their own 30-day TTL).
    cache_version: str = "1"
    llm: LLMSettings = Field(default_factory=LLMSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    support: SupportSettings = Field(default_factory=SupportSettings)
    venue: VenueSettings = Field(default_factory=VenueSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)

    @property
    def cache_path(self) -> Path:
        # CITECHECK_CACHE env overrides; tests should set it to a tmp path.
        raw = os.environ.get("CITECHECK_CACHE") or self.cache.path
        return Path(raw).expanduser()


def _domain(url: str) -> str:
    from urllib.parse import urlparse

    return ".".join((urlparse(url).hostname or "").split(".")[-2:])


def _retrieval_key(data: dict, env: dict[str, str], section: str,
                   default_env: str) -> str | None:
    llm = data.get("llm", {})
    sec = llm.get(section, {})
    name = sec.get("api_key_env", default_env)
    # the settings page stores whichever provider's key the user enters as
    # DASHSCOPE_API_KEY; never send it to a retrieval service on another
    # domain than the chat endpoint it was entered for
    if name == "DASHSCOPE_API_KEY":
        chat = llm.get("cloud", {}).get("base_url", CloudSettings().base_url)
        default_url = (EmbeddingSettings if section == "embedding" else RerankSettings)().base_url
        if _domain(chat) != _domain(sec.get("base_url", default_url)):
            return None
    return os.environ.get(name) or env.get(name)


def _load_settings() -> Settings:
    env = _load_dotenv(_ENV_PATH)
    toml_path = _CONFIG_PATH if _CONFIG_PATH.exists() else _CONFIG_EXAMPLE_PATH
    data: dict = {}
    if toml_path.exists():
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    return Settings(
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY") or env.get("DASHSCOPE_API_KEY"),
        crossref_mailto=os.environ.get("CROSSREF_MAILTO") or env.get("CROSSREF_MAILTO"),
        openalex_api_key=os.environ.get("OPENALEX_API_KEY") or env.get("OPENALEX_API_KEY"),
        s2_api_key=os.environ.get("S2_API_KEY") or env.get("S2_API_KEY"),
        embedding_api_key=_retrieval_key(
            data, env, "embedding", EmbeddingSettings().api_key_env),
        rerank_api_key=_retrieval_key(
            data, env, "rerank", RerankSettings().api_key_env),
        cache_version=str(data.get("cache_version", "1")),
        llm=LLMSettings(**data.get("llm", {})),
        retrieval=RetrievalSettings(**data.get("retrieval", {})),
        support=SupportSettings(**data.get("support", {})),
        venue=VenueSettings(**data.get("venue", {})),
        cache=CacheSettings(**data.get("cache", {})),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _load_settings()


def venue_model_enabled() -> bool:
    """期刊对标的模型细化开关 (settings page); CITECHECK_VENUE_MODEL=0
    turns it off for tests."""
    return get_settings().venue.model and os.environ.get("CITECHECK_VENUE_MODEL") != "0"
