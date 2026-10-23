import type { Library, LibraryDoc, LibraryLink } from '../types/report'

/** POST /library/scan response: the confirmation step before a run. */
export interface LibraryScan {
  paper: string
  candidates: string[]
  kind: string
  baseline: {
    source: 'exemplars' | 'builtin' | null
    name: string | null
    n_papers: number
  }
  library: Library
  references: ScanRef[]
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
  exemplars: number
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
  return {
    linked,
    review: review.size,
    none,
    exemplars: exemplarIds(scan, choice).length,
  }
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

/** Exemplars follow the user's edits: a PDF linked by hand is no longer
 *  a yardstick, one unlinked from its entry becomes one again. */
export function exemplarIds(scan: LibraryScan, choice: LinkChoice): string[] {
  const used = new Set(Object.values(choice).filter(Boolean))
  const venue = scan.library.venue
  if (!venue) return []
  return (scan.library.docs ?? [])
    .filter((d) => d.readable !== false && d.venue === venue && !used.has(d.id))
    .map((d) => d.id)
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
