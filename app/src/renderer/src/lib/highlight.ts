import type { ListItem, Severity } from './items'
import { sevRank } from './items'

export interface Segment {
  start: number
  end: number
  text: string
  /** null → unhighlighted plain text */
  severity: Severity | null
  itemIds: string[]
}

/** Split a paragraph's text into non-overlapping highlighted segments.
 * When anchors overlap, a segment takes the highest severity covering it
 * (high > medium > low > rev). */
export function segmentsForParagraph(
  text: string,
  items: ListItem[]
): Segment[] {
  const anchors = items
    .filter((i) => i.paragraphId !== null)
    .map((i) => {
      const a =
        i.kind === 'finding' ? i.finding?.anchor : i.revision?.anchor
      let s = Math.max(0, Math.min(text.length, a?.start ?? 0))
      let e = Math.max(0, Math.min(text.length, a?.end ?? 0))
      if (e <= s) {
        // zero-length anchors expand to the whole paragraph
        s = 0
        e = text.length
      }
      return { s, e, sev: i.severity, id: i.id }
    })
    .filter((a) => a.e > a.s)
  if (!anchors.length) return [{ start: 0, end: text.length, text, severity: null, itemIds: [] }]

  const bounds = new Set<number>([0, text.length])
  for (const a of anchors) {
    bounds.add(a.s)
    bounds.add(a.e)
  }
  const sorted = [...bounds].sort((x, y) => x - y)
  const out: Segment[] = []
  for (let i = 0; i + 1 < sorted.length; i++) {
    const s = sorted[i]
    const e = sorted[i + 1]
    const covering = anchors.filter((a) => a.s < e && a.e > s)
    if (!covering.length) {
      out.push({ start: s, end: e, text: text.slice(s, e), severity: null, itemIds: [] })
      continue
    }
    covering.sort((a, b) => sevRank(b.sev) - sevRank(a.sev))
    out.push({
      start: s,
      end: e,
      text: text.slice(s, e),
      severity: covering[0].sev,
      itemIds: covering.map((c) => c.id),
    })
  }
  return out
}

export const HL_CLASS: Record<Severity, string> = {
  high: 'hl-high',
  medium: 'hl-medium',
  low: 'hl-low',
  rev: 'hl-rev',
}
