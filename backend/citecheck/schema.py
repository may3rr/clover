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


class Paragraph(BaseModel):
    id: str
    section_id: str
    text: str
    char_offset: int


class CitationMarker(BaseModel):
    id: str
    paragraph_id: str
    start: int
    end: int
    raw: str
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
    move_after: str | None = None


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


class Report(BaseModel):
    document: Document
    sections: list[Section] = Field(default_factory=list)
    paragraphs: list[Paragraph] = Field(default_factory=list)
    markers: list[CitationMarker] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    ref_checks: list[RefCheck] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    support_checks: list[SupportCheck] = Field(default_factory=list)
    distribution: dict | None = None
    findings: list[Finding] = Field(default_factory=list)
    revisions: list[Revision] = Field(default_factory=list)
    meta: ReportMeta = Field(default_factory=ReportMeta)
