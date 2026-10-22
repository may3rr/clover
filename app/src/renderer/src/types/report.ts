/* GENERATED from backend/schema/report.schema.json — do not edit; run npm run gen:types */

export type Title = string | null;
export type Filename = string | null;
export type SourceFormat = "docx" | "tex";
export type Assets = string | null;
export type CitationStyle = "numeric" | "author_year" | "mixed" | "unknown";
export type ManagedBy = ("zotero" | "endnote") | null;
export type WordCount = number;
export type Id = string;
export type Title1 = string;
export type Canonical = "intro" | "related" | "method" | "experiment" | "discussion" | "conclusion" | "other";
export type HeadingParagraphId = string | null;
export type Sections = Section[];
export type Id1 = string;
export type SectionId = string;
export type Text = string;
export type CharOffset = number;
export type Start = number;
export type End = number;
export type Runs = [unknown, unknown][];
export type Math = MathSpan[];
export type Table = string;
export type Row = number;
export type Col = number;
export type Colspan = number;
export type Header = boolean;
export type Images = string[];
export type Caption = boolean;
export type Paragraphs = Paragraph[];
export type Id2 = string;
export type ParagraphId = string;
export type Start1 = number;
export type End1 = number;
export type Raw = string;
export type Kind = ("zotero" | "endnote" | "superscript" | "numeric" | "author_year" | "footnote" | "cite_key") | null;
export type RefIds = string[];
export type Keys = string[];
export type Markers = CitationMarker[];
export type Id3 = string;
export type Raw1 = string;
export type Title2 = string | null;
export type Authors = string[];
export type Year = number | null;
export type Venue = string | null;
export type Doi = string | null;
export type Lang = "en" | "zh" | "other";
export type ParagraphId1 = string | null;
export type Label = string | null;
export type Origin = "list" | "footnote";
export type Key = string | null;
export type Translation = string | null;
export type References = Reference[];
export type RefId = string;
export type Status = "verified" | "mismatch" | "not_found" | "unverifiable";
export type Matched = {
  [k: string]: unknown | undefined;
} | null;
export type Issues = string[];
export type Answered = string[];
export type RefChecks = RefCheck[];
export type Id4 = string;
export type ParagraphId2 = string;
export type Start2 = number;
export type End2 = number;
export type Text1 = string;
export type MarkerIds = string[];
export type Sentence = string | null;
export type Claims = Claim[];
export type ClaimId = string;
export type RefId1 = string;
export type Label1 = "supported" | "partial" | "unsupported" | "undetermined";
export type Evidence = string | null;
export type SourceKind = "abstract" | "fulltext" | "none";
export type Rationale = string;
export type SourceTitle = string | null;
export type SourceExcerpt = string | null;
export type EvidenceSpan = [unknown, unknown] | null;
export type OffTopic = boolean;
export type SourceFile = string | null;
export type SourcePage = number | null;
export type SupportChecks = SupportCheck[];
export type BenchmarkId = string;
export type BenchmarkName = string;
export type NPapers = number;
export type ComparableDensity = boolean;
export type Note = string | null;
export type SectionId1 = string;
export type Canonical1 = "intro" | "related" | "method" | "experiment" | "discussion" | "conclusion" | "other";
export type Title3 = string;
export type Words = number;
export type Citations = number;
export type Share = number;
export type Density = number;
export type Median = number;
export type Q1 = number;
export type Q3 = number;
export type ShareFlag = "below" | "within" | "above" | "na";
export type DensityFlag = "below" | "within" | "above" | "na";
export type Sections1 = SectionDist[];
export type ShareGe2 = number;
export type ShareGe3 = number;
export type ShareGe5 = number;
export type Functions = {
  [k: string]: number | undefined;
} | null;
export type Venue1 = string | null;
export type VenueSource = ("exemplars" | "builtin") | null;
export type Key1 = string;
export type Label2 = string;
export type Unit = string;
export type Value = number | null;
export type Flag = "below" | "within" | "above" | "na";
export type VenueStats = VenueStat[];
export type Id5 = string;
export type Layer = "authenticity" | "support" | "distribution" | "norms";
export type Severity = "high" | "medium" | "low";
export type ParagraphId3 = string;
export type Start3 = number;
export type End3 = number;
export type Loc = string | null;
export type Snippet = string | null;
export type SnippetHl = [unknown, unknown] | null;
export type Title4 = string;
export type Detail = string;
export type Refs = string[];
export type Findings = Finding[];
export type Id6 = string;
export type Kind1 = "typo" | "ref_reorder" | "marker_renumber";
export type Old = string;
export type New = string;
export type Reason = string;
export type MoveAfter = string | null;
export type Revisions = Revision[];
export type Status1 = "ok" | "unavailable";
export type VenueId = string;
export type VenueName = string;
export type Overall = "below" | "near" | "at" | "above" | "na";
export type Comment = string;
export type Key2 = string;
export type Label3 = string;
export type Tier = "below" | "near" | "at" | "above" | "na";
export type Note1 = string;
export type Dims = OverviewDim[];
export type Id7 = string;
export type Title5 = string;
export type Year1 = number | null;
export type Url = string;
export type Exemplars = ExemplarPaper[];
export type Note2 = string | null;
export type Folder = string;
export type Id8 = string;
export type Filename1 = string;
export type Duplicates = string[];
export type Pages = number;
export type Readable = boolean;
export type Source = "cnki_cover" | "cnki_citation" | "layout" | "doi" | "filename";
export type Title6 = string | null;
export type Authors1 = string[];
export type Venue2 = string | null;
export type Year2 = number | null;
export type Doi1 = string | null;
export type ArxivId = string | null;
export type Docs = LibraryDoc[];
export type RefId2 = string;
export type DocId = string;
export type Method = "doi" | "title" | "filename" | "llm" | "user";
export type Score = number;
export type Status2 = "auto" | "review" | "confirmed";
export type Links = LibraryLink[];
export type ExemplarIds = string[];
export type Venue3 = string | null;
export type Unsupported = string[];
export type Local = number;
export type Cloud = number;
export type Status3 = "pending" | "running" | "done" | "failed";
export type Error = string | null;
export type Findings1 = number;
export type DurationS = number;

export interface Report {
  document: Document;
  sections?: Sections;
  paragraphs?: Paragraphs;
  markers?: Markers;
  references?: References;
  ref_checks?: RefChecks;
  claims?: Claims;
  support_checks?: SupportChecks;
  distribution?: Distribution | null;
  findings?: Findings;
  revisions?: Revisions;
  overview?: Overview | null;
  library?: Library | null;
  meta?: ReportMeta;
}
export interface Document {
  title?: Title;
  filename?: Filename;
  source_format?: SourceFormat;
  assets?: Assets;
  citation_style?: CitationStyle;
  managed_by?: ManagedBy;
  word_count?: WordCount;
}
export interface Section {
  id: Id;
  title: Title1;
  canonical: Canonical;
  heading_paragraph_id?: HeadingParagraphId;
}
export interface Paragraph {
  id: Id1;
  section_id: SectionId;
  text: Text;
  char_offset: CharOffset;
  math?: Math;
  cell?: TableCell | null;
  images?: Images;
  caption?: Caption;
}
/**
 * LaTeX inline math inside Paragraph.text[start:end] (flattened text).
 * runs is the display form: (text, "" | "sub" | "sup") pieces.
 */
export interface MathSpan {
  start: Start;
  end: End;
  runs?: Runs;
}
/**
 * Where a paragraph sits in a table (several paragraphs may share a
 * cell). Tables are rendered as grids in the reading view; every cell
 * paragraph is still a normal Paragraph for anchors and checks.
 */
export interface TableCell {
  table: Table;
  row: Row;
  col: Col;
  colspan?: Colspan;
  header?: Header;
}
export interface CitationMarker {
  id: Id2;
  paragraph_id: ParagraphId;
  start: Start1;
  end: End1;
  raw: Raw;
  kind?: Kind;
  ref_ids?: RefIds;
  keys?: Keys;
}
export interface Reference {
  id: Id3;
  raw: Raw1;
  title?: Title2;
  authors?: Authors;
  year?: Year;
  venue?: Venue;
  doi?: Doi;
  lang?: Lang;
  paragraph_id?: ParagraphId1;
  label?: Label;
  origin?: Origin;
  key?: Key;
  translation?: Translation;
}
export interface RefCheck {
  ref_id: RefId;
  status: Status;
  matched?: Matched;
  issues?: Issues;
  answered?: Answered;
}
export interface Claim {
  id: Id4;
  paragraph_id: ParagraphId2;
  start: Start2;
  end: End2;
  text: Text1;
  marker_ids?: MarkerIds;
  sentence?: Sentence;
}
export interface SupportCheck {
  claim_id: ClaimId;
  ref_id: RefId1;
  label: Label1;
  evidence?: Evidence;
  source_kind: SourceKind;
  rationale: Rationale;
  source_title?: SourceTitle;
  source_excerpt?: SourceExcerpt;
  evidence_span?: EvidenceSpan;
  off_topic?: OffTopic;
  source_file?: SourceFile;
  source_page?: SourcePage;
}
export interface Distribution {
  benchmark_id: BenchmarkId;
  benchmark_name: BenchmarkName;
  n_papers: NPapers;
  comparable_density: ComparableDensity;
  note?: Note;
  sections?: Sections1;
  sentence_refs?: SentenceRefs | null;
  functions?: Functions;
  marker_functions?: MarkerFunctions;
  venue?: Venue1;
  venue_source?: VenueSource;
  venue_stats?: VenueStats;
}
export interface SectionDist {
  section_id: SectionId1;
  canonical: Canonical1;
  title: Title3;
  words: Words;
  citations: Citations;
  share: Share;
  density: Density;
  bench_share?: Stat | null;
  bench_density?: Stat | null;
  share_flag?: ShareFlag;
  density_flag?: DensityFlag;
}
export interface Stat {
  median: Median;
  q1: Q1;
  q3: Q3;
}
export interface SentenceRefs {
  share_ge2: ShareGe2;
  share_ge3: ShareGe3;
  share_ge5: ShareGe5;
  bench_ge2?: Stat | null;
  bench_ge3?: Stat | null;
  bench_ge5?: Stat | null;
}
export interface MarkerFunctions {
  [k: string]: string | undefined;
}
/**
 * A journal-level indicator: the manuscript vs the target journal's
 * papers (share values are fractions, unit "%").
 */
export interface VenueStat {
  key: Key1;
  label: Label2;
  unit: Unit;
  value?: Value;
  bench?: Stat | null;
  flag?: Flag;
}
export interface Finding {
  id: Id5;
  layer: Layer;
  severity: Severity;
  anchor?: Anchor | null;
  title: Title4;
  detail: Detail;
  refs?: Refs;
}
export interface Anchor {
  paragraph_id: ParagraphId3;
  start: Start3;
  end: End3;
  loc?: Loc;
  snippet?: Snippet;
  snippet_hl?: SnippetHl;
}
export interface Revision {
  id: Id6;
  kind: Kind1;
  anchor: Anchor;
  old: Old;
  new: New;
  reason: Reason;
  move_after?: MoveAfter;
}
/**
 * Venue-level read of the manuscript: where it sits against a few
 * recent papers of the target venue. A coarse tier plus a direction —
 * deliberately not edit-level advice (AGENTS §2).
 */
export interface Overview {
  status?: Status1;
  venue_id: VenueId;
  venue_name: VenueName;
  overall?: Overall;
  comment?: Comment;
  dims?: Dims;
  exemplars?: Exemplars;
  manuscript?: Manuscript;
  note?: Note2;
}
export interface OverviewDim {
  key: Key2;
  label: Label3;
  tier?: Tier;
  note?: Note1;
}
/**
 * A recently published paper from the target venue, used as a yardstick.
 */
export interface ExemplarPaper {
  id: Id7;
  title: Title5;
  year?: Year1;
  url: Url;
  stats?: Stats;
}
export interface Stats {
  [k: string]: number | boolean | null | undefined;
}
export interface Manuscript {
  [k: string]: number | boolean | null | undefined;
}
export interface Library {
  folder: Folder;
  docs?: Docs;
  links?: Links;
  exemplar_ids?: ExemplarIds;
  venue?: Venue3;
  unsupported?: Unsupported;
}
/**
 * A PDF in the user's reference folder (文献文件夹).
 */
export interface LibraryDoc {
  id: Id8;
  filename: Filename1;
  duplicates?: Duplicates;
  pages?: Pages;
  readable?: Readable;
  source?: Source;
  title?: Title6;
  authors?: Authors1;
  venue?: Venue2;
  year?: Year2;
  doi?: Doi1;
  arxiv_id?: ArxivId;
}
/**
 * Reference entry -> local PDF. ``review`` links came from a weak
 * match (or the model) and wait for the user in the confirmation step.
 */
export interface LibraryLink {
  ref_id: RefId2;
  doc_id: DocId;
  method: Method;
  score: Score;
  status?: Status2;
}
export interface ReportMeta {
  llm_calls?: LLMCalls;
  layers?: Layers;
  duration_s?: DurationS;
  token_usage?: TokenUsage;
  timings?: Timings;
}
export interface LLMCalls {
  local?: Local;
  cloud?: Cloud;
}
export interface Layers {
  [k: string]: LayerStatus | undefined;
}
export interface LayerStatus {
  status?: Status3;
  error?: Error;
  findings?: Findings1;
}
export interface TokenUsage {
  [k: string]:
    | {
        [k: string]: number | undefined;
      }
    | undefined;
}
export interface Timings {
  [k: string]: unknown | undefined;
}
