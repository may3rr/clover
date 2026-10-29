import type { Library, LibraryDoc, LibraryLink } from '../types/report'

/** A journal the registry knows: rules, maybe a built-in baseline. */
export interface VenueEntry {
  id: string
  name: string
  n_papers: number
}

/** POST /library/scan response: the confirmation step before a run. */
export interface LibraryScan {
  paper: string
  candidates: string[]
  kind: string
  entry?: VenueEntry | null
  paper_type?: 'research' | 'review'
  library: Library
  references: ScanRef[]
}

/** The target journal and its exemplar candidates; POST /library/venue
 *  returns a fresh one when the user changes the journal. */
export interface VenueState {
  venue: string | null
  source: Library['venue_source']
  matchIds: string[]
  /** the default selection: matches of the manuscript's paper type */
  defaultIds: string[]
  docs: LibraryDoc[]
  entry: VenueEntry | null
}

export function venueState(scan: LibraryScan): VenueState {
  return {
    venue: scan.library.venue ?? null,
    source: scan.library.venue_source ?? null,
    matchIds: scan.library.venue_match_ids ?? [],
    defaultIds: scan.library.exemplar_ids ?? [],
    docs: scan.library.docs ?? [],
    entry: scan.entry ?? null,
  }
}

export interface ScanRef {
  id: string
  label: string | null
  title: string | null
  authors: string[]
  year: number | null
  lang: string
  raw: string
}

export type LinkFilter = 'all' | 'review' | 'linked' | 'none'

/** ref_id -> chosen doc id ('' = no PDF). */
export type LinkChoice = Record<string, string>

export function initialChoice(lib: Library): LinkChoice {
  const out: LinkChoice = {}
  for (const l of lib.links ?? []) out[l.ref_id] = l.doc_id
  return out
}

export interface LinkCounts {
  linked: number
  review: number
  none: number
}

/** Rows still waiting for the user: model picks they haven't touched. */
export function counts(
  scan: LibraryScan,
  choice: LinkChoice,
  touched: Set<string>
): LinkCounts {
  const review = new Set(
    (scan.library.links ?? [])
      .filter((l) => l.status === 'review' && !touched.has(l.ref_id))
      .map((l) => l.ref_id)
  )
  let linked = 0
  let none = 0
  for (const r of scan.references) {
    if (review.has(r.id)) continue
    if (choice[r.id]) linked++
    else none++
  }
  return { linked, review: review.size, none }
}

export function rowState(
  scan: LibraryScan,
  choice: LinkChoice,
  touched: Set<string>,
  refId: string
): 'review' | 'linked' | 'none' {
  const l = (scan.library.links ?? []).find((x) => x.ref_id === refId)
  if (l?.status === 'review' && !touched.has(refId)) return 'review'
  return choice[refId] ? 'linked' : 'none'
}

/** PDFs that can serve as exemplars: readable and not linked to an
 *  entry (a PDF linked by hand stops being one, one unlinked becomes one
 *  again). The target journal's matches come first. */
export function exemplarCandidates(vs: VenueState, choice: LinkChoice): LibraryDoc[] {
  const used = new Set(Object.values(choice).filter(Boolean))
  const match = new Set(vs.matchIds)
  return vs.docs
    .filter((d) => d.readable !== false && !used.has(d.id))
    .sort(
      (a, b) =>
        Number(match.has(b.id)) - Number(match.has(a.id)) ||
        (a.title ?? a.filename).localeCompare(b.title ?? b.filename, 'zh')
    )
}

/** The user's selection, minus PDFs that have since been linked. */
export function pickedExemplars(
  picked: Set<string>,
  vs: VenueState,
  choice: LinkChoice
): string[] {
  return exemplarCandidates(vs, choice)
    .map((d) => d.id)
    .filter((id) => picked.has(id))
}

export const MIN_EXEMPLARS = 3

/** What the run will compare against, in one sentence. */
export function baselineText(vs: VenueState, nPicked: number): string {
  if (!vs.venue)
    return '没有填写目标期刊，这次不对标。填写后，参考文献和文件夹里该刊的论文会作为对标范文。'
  return (
    `体检时会从参考文献中找出《${vs.venue}》的论文，连同这里勾选的 ${nPicked} 篇一起作为对标范文，` +
    `合计不少于 ${MIN_EXEMPLARS} 篇才对标。`
  )
}

const VIA: Record<string, string> = {
  cnki_cover: '知网封面刊名',
  cnki_citation: '引用本文条目',
  doi_prefix: 'DOI 前缀',
  issn: 'ISSN 或 CN 号',
  header: '页眉页脚刊名',
  model: '模型从首页读出的刊名',
}

/** "《数据分析与知识发现》，2026，知网封面刊名，综述" */
export function exemplarMeta(d: LibraryDoc): string {
  const bits = [d.venue ? `《${d.venue}》` : '刊名未知']
  if (d.year) bits.push(String(d.year))
  if (d.venue && d.venue_via) bits.push(VIA[d.venue_via] ?? '')
  if (d.paper_type === 'review') bits.push('综述')
  return bits.filter(Boolean).join('，')
}

/** Links to send with /analyze — starting the run confirms every row.
 *  Unchanged automatic links keep their method; edited ones are "user". */
export function finalLinks(scan: LibraryScan, choice: LinkChoice): LibraryLink[] {
  const auto = new Map((scan.library.links ?? []).map((l) => [l.ref_id, l]))
  const out: LibraryLink[] = []
  for (const r of scan.references) {
    const doc = choice[r.id]
    if (!doc) continue
    const a = auto.get(r.id)
    out.push(
      a && a.doc_id === doc
        ? { ...a, status: 'confirmed' }
        : { ref_id: r.id, doc_id: doc, method: 'user', score: 100, status: 'confirmed' }
    )
  }
  return out
}

/** A PDF's one-line description for menus and rows. */
export function docLabel(d: LibraryDoc): string {
  const who = (d.authors ?? [])[0]
  const bits = [d.title || d.filename]
  if (who) bits.push(who)
  if (d.year) bits.push(String(d.year))
  return bits.join('，')
}

export function baseName(p: string): string {
  return p.replace(/\/+$/, '').split('/').pop() ?? p
}
