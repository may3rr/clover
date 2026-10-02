// Document skeleton data — pure functions, vitest-covered.
// The backend emits the outline on the "parsed" event; shots synthesize
// the same shape from a Report via outlineFromReport.

import type { Report } from '../types/report'

export interface SkPara {
  id: string
  length: number
  /** citation marker positions, relative 0..1 within the paragraph */
  markers: number[]
  /** section heading paragraph — renders as the section label bar */
  heading?: boolean
}

export interface SkSection {
  id: string
  title: string
  canonical: string
  paragraphs: SkPara[]
}

export interface Outline {
  title: string | null
  sections: SkSection[]
  references: number
}

export interface SkAnchor {
  paragraph_id: string
  start_rel: number
  end_rel: number
  severity: string
}

// ------------------------------------------------------------ layout

export const CHARS_PER_LINE = 90
export const LINE_H = 7 // 3px bar + 4px gap
export const HEAD_H = 15 // title text + gap
export const PAGE_PAD = 10
export const PAGE_W = 124
export const PAGE_H = 170
export const MAX_PAGES = 4
export const MIN_PAGES = 2
export const MAX_REF_BARS = 10

export interface SkLine {
  kind: 'line' | 'heading' | 'ref'
  /** unit key used to light the bar when a layer lands */
  key: string
  /** title text for heading units */
  text?: string
  /** para this line belongs to */
  paraId?: string
  /** char range this line covers inside the paragraph */
  charStart?: number
  charEnd?: number
  /** marker x-positions (0..1 across the bar) on this line */
  dots?: number[]
  /** last line of a paragraph renders shorter */
  short?: boolean
}

export type SkPage = SkLine[]

export interface SkLayout {
  pages: SkPage[]
  /** unit key -> page index (for the pop animation) */
  pageOf: Record<string, number>
}

const LINES_PER_PAGE = Math.floor((PAGE_H - 2 * PAGE_PAD) / LINE_H) // 21

/** Flow paragraphs into page thumbnails: ceil(len/90) bars per paragraph
 * (scaled down when the paper doesn't fit), heading bars with real
 * section titles, marker dots at their relative positions, short bars
 * for the reference list at the end. */
export function layoutSkeleton(outline: Outline): SkLayout {
  const headingCount = outline.sections.filter((s) => s.title).length
  const refBars = Math.min(outline.references, MAX_REF_BARS)

  // raw line demand per paragraph
  const raw: { para: SkPara; n: number }[] = []
  let total = 0
  for (const s of outline.sections) {
    for (const p of s.paragraphs) {
      if (p.heading) continue
      const n = Math.max(1, Math.ceil(p.length / CHARS_PER_LINE))
      raw.push({ para: p, n })
      total += n
    }
  }

  // fit into at most MAX_PAGES worth of lines
  const pageCap = LINES_PER_PAGE // unit height differs; approximate with lines
  const budgetUnits =
    MAX_PAGES * pageCap - headingCount * 2 - refBars - outline.sections.length
  const scale = total > 0 ? Math.min(1, budgetUnits / total) : 1

  // build flat unit list
  const units: SkLine[] = []
  for (const s of outline.sections) {
    units.push({ kind: 'heading', key: `h-${s.id}`, text: s.title })
    for (const p of s.paragraphs) {
      if (p.heading) continue
      const n = Math.max(1, Math.round((p.length / CHARS_PER_LINE) * scale))
      const per = p.length / n
      for (let i = 0; i < n; i++) {
        const charStart = i * per
        const charEnd = (i + 1) * per
        units.push({
          kind: 'line',
          key: `${p.id}#${i}`,
          paraId: p.id,
          charStart,
          charEnd,
          short: i === n - 1,
          dots: p.markers
            .map((m) => m * p.length)
            .filter((c) => c >= charStart && c < charEnd)
            .map((c) => Math.min(0.97, (c - charStart) / Math.max(per, 1))),
        })
      }
    }
  }
  for (let i = 0; i < refBars; i++) {
    units.push({ kind: 'ref', key: `r-${i}`, short: true })
  }

  // paginate: heading counts as ~2 lines tall
  const pages: SkPage[] = []
  const pageOf: Record<string, number> = {}
  let page: SkPage = []
  let used = 0
  for (const u of units) {
    const h = u.kind === 'heading' ? 2 : 1
    if (used + h > pageCap && page.length) {
      pages.push(page)
      page = []
      used = 0
    }
    page.push(u)
    used += h
  }
  if (page.length) pages.push(page)
  pages.forEach((pg, i) => pg.forEach((u) => (pageOf[u.key] = i)))
  return { pages, pageOf }
}

/** Anchor -> skeleton unit key + page. start_rel * paragraph length gives
 * the char offset; the unit whose char range covers it lights up. */
export function anchorUnit(
  layout: SkLayout,
  outline: Outline,
  anchor: SkAnchor
): { key: string; page: number } | null {
  let para: SkPara | null = null
  for (const s of outline.sections) {
    para = s.paragraphs.find((p) => p.id === anchor.paragraph_id) ?? null
    if (para) break
  }
  if (!para) return null
  if (para.heading) {
    const key = `h-${outline.sections.find((s) =>
      s.paragraphs.some((p) => p.id === para!.id))?.id ?? ''}`
    const page = layout.pageOf[key]
    return page === undefined ? null : { key, page }
  }
  const c = anchor.start_rel * para.length
  for (const pg of layout.pages) {
    const u = pg.find(
      (x) =>
        x.paraId === para!.id &&
        x.charStart !== undefined &&
        x.charEnd !== undefined &&
        c >= x.charStart &&
        c < x.charEnd
    )
    if (u) return { key: u.key, page: layout.pageOf[u.key] }
  }
  // anchor past the scaled-down end -> last line of the paragraph
  const last = [...layout.pages.flat()]
    .reverse()
    .find((x) => x.paraId === para!.id)
  return last ? { key: last.key, page: layout.pageOf[last.key] } : null
}

// ------------------------------------------------- shot/demo helpers

/** Build the same outline shape from a finished Report (shots mode). */
export function outlineFromReport(report: Report): Outline {
  const headingIds = new Set(
    (report.sections ?? [])
      .map((s) => s.heading_paragraph_id)
      .filter(Boolean) as string[]
  )
  const lenByPara = new Map(
    (report.paragraphs ?? []).map((p) => [p.id ?? '', Math.max(1, (p.text ?? '').length)])
  )
  const markersByPara = new Map<string, number[]>()
  for (const m of report.markers ?? []) {
    const arr = markersByPara.get(m.paragraph_id ?? '') ?? []
    arr.push((m.start ?? 0) / (lenByPara.get(m.paragraph_id ?? '') ?? 1))
    markersByPara.set(m.paragraph_id ?? '', arr)
  }
  return {
    title: report.document.title ?? null,
    sections: (report.sections ?? []).map((s) => ({
      id: s.id ?? '',
      title: s.title ?? '',
      canonical: s.canonical ?? 'other',
      paragraphs: (report.paragraphs ?? [])
        .filter((p) => p.section_id === s.id)
        .map((p) => ({
          id: p.id ?? '',
          length: (p.text ?? '').length,
          markers: markersByPara.get(p.id ?? '') ?? [],
          heading: headingIds.has(p.id ?? ''),
        })),
    })),
    references: (report.references ?? []).length,
  }
}

/** Report findings -> per-layer skeleton anchors (shots mode). */
export function anchorsFromReport(report: Report): Record<string, SkAnchor[]> {
  const lenByPara = new Map(
    (report.paragraphs ?? []).map((p) => [p.id ?? '', Math.max(1, (p.text ?? '').length)])
  )
  const out: Record<string, SkAnchor[]> = {}
  for (const f of report.findings ?? []) {
    if (!f.anchor?.paragraph_id) continue
    const n = lenByPara.get(f.anchor.paragraph_id) ?? 1
    const a: SkAnchor = {
      paragraph_id: f.anchor.paragraph_id,
      start_rel: Math.min(1, (f.anchor.start ?? 0) / n),
      end_rel: Math.min(1, (f.anchor.end ?? 0) / n),
      severity: f.severity ?? 'low',
    }
    ;(out[f.layer ?? 'norms'] ??= []).push(a)
  }
  return out
}
