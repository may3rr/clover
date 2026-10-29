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
    # LaTeX 源码位置 "sections/intro.tex:42"（docx 为 None）
    loc: str | None = None
    # LaTeX only: the source line(s) the anchor covers, and the anchored
    # range inside that snippet when it maps verbatim
    snippet: str | None = None
    snippet_hl: tuple[int, int] | None = None


CanonicalSection = Literal[
    "intro", "related", "method", "experiment", "discussion", "conclusion", "other"
]


class Section(BaseModel):
    id: str
    title: str
    canonical: CanonicalSection
    heading_paragraph_id: str | None = None  # None for the leading untitled section


class MathSpan(BaseModel):
    """LaTeX inline math inside Paragraph.text[start:end] (flattened text).
    runs is the display form: (text, "" | "sub" | "sup") pieces."""
    start: int
    end: int
    runs: list[tuple[str, Literal["", "sub", "sup"]]] = Field(
        default_factory=list)


class TableCell(BaseModel):
    """Where a paragraph sits in a table (several paragraphs may share a
    cell). Tables are rendered as grids in the reading view; every cell
    paragraph is still a normal Paragraph for anchors and checks."""
    table: str
    row: int
    col: int
    colspan: int = 1
    header: bool = False


class Paragraph(BaseModel):
    id: str
    section_id: str
    text: str
    char_offset: int
    # LaTeX only: inline math spans for the reading view
    math: list[MathSpan] = Field(default_factory=list)
    cell: TableCell | None = None
    # image assets shown above this paragraph's text (Document.assets
    # names the bundle they are served from)
    images: list[str] = Field(default_factory=list)
    # figure/table caption: shown in the secondary caption style
    caption: bool = False


MarkerKind = Literal[
    "zotero", "endnote", "superscript", "numeric", "author_year", "footnote",
    "cite_key",
]


class CitationMarker(BaseModel):
    id: str
    paragraph_id: str
    start: int
    end: int
    raw: str
    kind: MarkerKind | None = None  # how the marker was detected
    ref_ids: list[str] = Field(default_factory=list)
    # cite_key only: the bib keys inside the \cite{...} command, in order
    keys: list[str] = Field(default_factory=list)


CitationStyle = Literal["numeric", "author_year", "mixed", "unknown"]
RefManager = Literal["zotero", "endnote"]


class Document(BaseModel):
    title: str | None = None
    filename: str | None = None
    source_format: Literal["docx", "tex"] = "docx"
    # image bundle id: GET /assets/{assets}/{name} serves Paragraph.images
    assets: str | None = None
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
    # "list" = an entry in the bibliography block; "footnote" = promoted
    # from a footnote/endnote body (paragraph_id then points at the
    # paragraph that cites it). Positional algorithms (reorder, numeric
    # fallback resolution) must ignore non-"list" entries.
    origin: Literal["list", "footnote"] = "list"
    key: str | None = None  # bib cite key (latex sources only)
    # English rendering appended to a Chinese entry (GB/T 7714 journals
    # such as DAKD require one); None when absent
    translation: str | None = None


RefStatus = Literal["verified", "mismatch", "not_found", "unverifiable"]


class RefCheck(BaseModel):
    ref_id: str
    status: RefStatus
    matched: dict | None = None
    issues: list[str] = Field(default_factory=list)
    # which sources actually answered (a 429/timeout is NOT an answer)
    answered: list[str] = Field(default_factory=list)


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
    # label stays undetermined; set when the cited work's subject is
    # unrelated to the claim (checked by the review model) — a likely
    # miscitation, surfaced as its own finding
    off_topic: bool = False
    # evidence from the user's own PDF (文献文件夹): file name and the
    # 1-based page the evidence sits on
    source_file: str | None = None
    source_page: int | None = None


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
    # distribution only: keys into Distribution.venue_metrics that back
    # this finding (the detail view lists each exemplar's value)
    metrics: list[str] = Field(default_factory=list)


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


class VenueStat(BaseModel):
    """A journal-level indicator: the manuscript vs the target journal's
    papers (share values are fractions, unit "%")."""
    key: str
    label: str
    unit: str
    value: float | None = None
    bench: Stat | None = None
    flag: DistFlag = "na"


VenueMetricGroup = Literal["structure", "distribution", "references", "functions",
                          "elements", "length"]


class ExemplarValue(BaseModel):
    """One exemplar's value of a metric, and where in its PDF it comes
    from (1-based page, a verbatim line such as the section heading or
    the model's evidence)."""
    doc_id: str
    value: float | None = None
    page: int | None = None
    quote: str | None = None


class VenueMetric(BaseModel):
    """The manuscript vs the target journal's exemplars on one measure.
    kind "share" values are fractions (unit "%"); kind "bool" compares
    the manuscript's yes/no against ``rate``, the share of exemplars
    with a yes."""
    key: str
    group: VenueMetricGroup
    label: str
    unit: str = ""
    kind: Literal["number", "share", "bool"] = "number"
    value: float | None = None
    bench: Stat | None = None
    rate: float | None = None
    flag: DistFlag = "na"
    exemplars: list[ExemplarValue] = Field(default_factory=list)
    # manuscript paragraphs behind the value, and the model's evidence
    anchors: list[Anchor] = Field(default_factory=list)
    quote: str | None = None


class ExemplarInfo(BaseModel):
    """A paper of the target venue the baseline was built from (or found
    for it): one of the manuscript's references, or an uncited PDF in
    the reference folder."""
    doc_id: str
    filename: str = ""  # local PDF; "" when the text came from the web
    title: str | None = None
    year: int | None = None
    paper_type: Literal["research", "review"] = "research"
    origin: Literal["cited", "folder"] = "folder"
    ref_id: str | None = None  # cited: the manuscript's reference
    label: str | None = None  # cited: its label in the manuscript, "12"
    url: str | None = None  # cited without a local PDF: the open-access PDF
    used: bool = True
    note: str | None = None  # why it could not be used
    similar: bool = False  # among the closest to the manuscript's topic


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
    # venue benchmarking: the target the user typed and the papers of it
    # the baseline was built from (cited references, folder PDFs);
    # "builtin" appears only in reports stored before F34
    venue: str | None = None
    venue_source: Literal["exemplars", "builtin"] | None = None
    venue_stats: list[VenueStat] = Field(default_factory=list)
    # exemplar baselines only: every measure with per-exemplar values
    exemplars: list[ExemplarInfo] = Field(default_factory=list)
    venue_metrics: list[VenueMetric] = Field(default_factory=list)


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
    # {"parse": s, "layers": {layer: s}, "sources": {src: {calls, seconds, cached}}}
    timings: dict = Field(default_factory=dict)


OverviewTier = Literal["below", "near", "at", "above", "na"]


class ExemplarPaper(BaseModel):
    """A paper of the target venue the critic compared against: one of
    the manuscript's references or an uncited PDF in the folder."""
    id: str
    title: str
    year: int | None = None
    url: str | None = None
    origin: Literal["cited", "folder"] = "folder"
    label: str | None = None  # cited: its label in the manuscript, "12"
    # n_datasets / n_baselines / n_tables / n_figures / has_ablation /
    # has_human_eval / has_error_analysis / has_limitations (None = unknown)
    stats: dict[str, int | bool | None] = Field(default_factory=dict)


class OverviewDim(BaseModel):
    key: str  # experiments | analysis | literature | citations | completeness
    label: str
    tier: OverviewTier = "na"
    note: str = ""


class Overview(BaseModel):
    """Venue-level read of the manuscript: where it sits against a few
    recent papers of the target venue. A coarse tier plus a direction —
    deliberately not edit-level advice (AGENTS §2)."""
    # pending：报告已经打开，对标还在后台计算（见 pipeline 的 on_report）
    status: Literal["ok", "unavailable", "pending"] = "ok"
    venue_id: str
    venue_name: str
    overall: OverviewTier = "na"
    comment: str = ""
    dims: list[OverviewDim] = Field(default_factory=list)
    exemplars: list[ExemplarPaper] = Field(default_factory=list)
    manuscript: dict[str, int | bool | float | None] = Field(default_factory=dict)
    note: str | None = None  # why it is unavailable, for the UI


LibrarySource = Literal["cnki_cover", "cnki_citation", "layout", "doi", "filename"]


class LibraryDoc(BaseModel):
    """A PDF in the user's reference folder (文献文件夹)."""
    id: str  # first 16 hex chars of the file's sha256
    filename: str
    duplicates: list[str] = Field(default_factory=list)  # byte-identical copies
    pages: int = 0
    readable: bool = True  # False: scanned / encrypted, no text layer
    source: LibrarySource = "filename"  # where title/authors came from
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    # how the journal was recognised (None: unknown) and the paper type
    venue_via: Literal["cnki_cover", "cnki_citation", "doi_prefix", "issn",
                       "header", "model"] | None = None
    paper_type: Literal["research", "review"] = "research"


LinkMethod = Literal["doi", "title", "filename", "llm", "user"]


class LibraryLink(BaseModel):
    """Reference entry -> local PDF. ``review`` links came from a weak
    match (or the model) and wait for the user in the confirmation step."""
    ref_id: str
    doc_id: str
    method: LinkMethod
    score: float  # 0-100
    status: Literal["auto", "review", "confirmed"] = "auto"


class Library(BaseModel):
    folder: str
    docs: list[LibraryDoc] = Field(default_factory=list)
    links: list[LibraryLink] = Field(default_factory=list)
    # unlinked PDFs published in the target venue: yardsticks for 对标
    exemplar_ids: list[str] = Field(default_factory=list)
    venue: str | None = None  # target venue the exemplars come from
    # user (typed on the confirmation page) | folder (most uncited PDFs) |
    # manuscript (template traces on its first page)
    venue_source: Literal["user", "folder", "manuscript"] | None = None
    # uncited PDFs recognised as the target journal's; exemplar_ids is the
    # selection (default: those of the manuscript's paper type)
    venue_match_ids: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)  # .caj etc.


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
    overview: Overview | None = None
    library: Library | None = None
    meta: ReportMeta = Field(default_factory=ReportMeta)
