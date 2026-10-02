"""Data model for citecheck, implementing AGENTS.md §5.1.

Frontend TypeScript types are generated from this module's JSON Schema
(see backend/scripts/export_schema.py); never hand-write a second copy.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Anchor(BaseModel):
    paragraph_id: str
    start: int
    end: int


CanonicalSection = Literal[
    "intro", "related", "method", "experiment", "discussion", "conclusion", "other"
]


class Section(BaseModel):
    id: str
    title: str
    canonical: CanonicalSection
    heading_paragraph_id: str | None = None  # None for the leading untitled section


class Paragraph(BaseModel):
    id: str
    section_id: str
    text: str
    char_offset: int


MarkerKind = Literal["zotero", "endnote", "superscript", "numeric", "author_year"]


class CitationMarker(BaseModel):
    id: str
    paragraph_id: str
    start: int
    end: int
    raw: str
    kind: MarkerKind | None = None  # how the marker was detected
    ref_ids: list[str] = Field(default_factory=list)


CitationStyle = Literal["numeric", "author_year", "mixed", "unknown"]
RefManager = Literal["zotero", "endnote"]


class Document(BaseModel):
    title: str | None = None
    filename: str | None = None
    citation_style: CitationStyle = "unknown"
    managed_by: RefManager | None = None
    word_count: int = 0


RefLang = Literal["en", "zh", "other"]


class Reference(BaseModel):
    id: str
    raw: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    lang: RefLang = "other"
    paragraph_id: str | None = None
    label: str | None = None


RefStatus = Literal["verified", "mismatch", "not_found", "unverifiable"]


class RefCheck(BaseModel):
    ref_id: str
    status: RefStatus
    matched: dict | None = None
    issues: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    id: str
    paragraph_id: str
    start: int
    end: int
    text: str
    marker_ids: list[str] = Field(default_factory=list)
    sentence: str | None = None  # full containing sentence, shown to the judge


SupportLabel = Literal["supported", "partial", "unsupported", "undetermined"]
SourceKind = Literal["abstract", "fulltext", "none"]


class SupportCheck(BaseModel):
    claim_id: str
    ref_id: str
    label: SupportLabel
    evidence: str | None = None
    source_kind: SourceKind
    rationale: str
    source_title: str | None = None
    source_excerpt: str | None = None
    evidence_span: tuple[int, int] | None = None


FindingLayer = Literal["authenticity", "support", "distribution", "norms"]
Severity = Literal["high", "medium", "low"]


class Finding(BaseModel):
    id: str
    layer: FindingLayer
    severity: Severity
    anchor: Anchor | None = None
    title: str
    detail: str
    refs: list[str] = Field(default_factory=list)


RevisionKind = Literal["typo", "ref_reorder", "marker_renumber"]


class Revision(BaseModel):
    id: str
    kind: RevisionKind
    anchor: Anchor
    old: str
    new: str
    reason: str
    # ref_reorder only: paragraph_id of the entry's predecessor in the
    # target order, or "__start__" when it becomes the first entry. The
    # exporter processes moved entries in target order and inserts each
    # copy after the predecessor's current element (the inserted copy when
    # the predecessor itself moved); "__start__" inserts before the first
    # original reference paragraph. None = in-place edit, no move.
    move_after: str | None = None


class Stat(BaseModel):
    median: float
    q1: float
    q3: float


DistFlag = Literal["below", "within", "above", "na"]


class SectionDist(BaseModel):
    section_id: str
    canonical: CanonicalSection
    title: str
    words: int
    citations: int  # ref ids across markers in the section, with multiplicity
    share: float  # section citations / paper citations
    density: float  # citations per 1000 words
    bench_share: Stat | None = None
    bench_density: Stat | None = None
    share_flag: DistFlag = "na"
    density_flag: DistFlag = "na"


class SentenceRefs(BaseModel):
    share_ge2: float
    share_ge3: float
    share_ge5: float
    bench_ge2: Stat | None = None
    bench_ge3: Stat | None = None
    bench_ge5: Stat | None = None


class Distribution(BaseModel):
    benchmark_id: str
    benchmark_name: str
    n_papers: int
    comparable_density: bool
    note: str | None = None
    sections: list[SectionDist] = Field(default_factory=list)
    sentence_refs: SentenceRefs | None = None
    functions: dict[str, int] | None = None
    marker_functions: dict[str, str] = Field(default_factory=dict)


LayerStatusValue = Literal["pending", "running", "done", "failed"]


class LayerStatus(BaseModel):
    status: LayerStatusValue = "pending"
    error: str | None = None
    findings: int = 0


class LLMCalls(BaseModel):
    local: int = 0
    cloud: int = 0


class ReportMeta(BaseModel):
    llm_calls: LLMCalls = Field(default_factory=LLMCalls)
    layers: dict[str, LayerStatus] = Field(default_factory=dict)
    duration_s: float = 0.0
    # model name -> {"prompt": tokens, "completion": tokens} (uncached calls)
    token_usage: dict[str, dict[str, int]] = Field(default_factory=dict)


class Report(BaseModel):
    document: Document
    sections: list[Section] = Field(default_factory=list)
    paragraphs: list[Paragraph] = Field(default_factory=list)
    markers: list[CitationMarker] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    ref_checks: list[RefCheck] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    support_checks: list[SupportCheck] = Field(default_factory=list)
    distribution: Distribution | None = None
    findings: list[Finding] = Field(default_factory=list)
    revisions: list[Revision] = Field(default_factory=list)
    meta: ReportMeta = Field(default_factory=ReportMeta)
