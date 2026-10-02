import type { Finding, Report, Revision } from '../types/report'

export type Severity = 'high' | 'medium' | 'low' | 'rev'

export interface ListItem {
  id: string
  kind: 'finding' | 'revision'
  /** 'norms' for revisions — they filter under 格式规范 */
  layer: string
  severity: Severity
  title: string
  detail: string
  paragraphId: string | null
  start: number
  finding?: Finding
  revision?: Revision
}

const SEV_RANK: Record<Severity, number> = { high: 3, medium: 2, low: 1, rev: 0 }

export function sevRank(s: Severity): number {
  return SEV_RANK[s]
}

/** The right-column list: findings + revisions in document order.
 * Anchor-less items come first, then paragraph order, then anchor start. */
export function buildItems(report: Report): ListItem[] {
  const paraPos = new Map<string, number>()
  ;(report.paragraphs ?? []).forEach((p, i) => paraPos.set(p.id ?? '', i))

  const items: ListItem[] = []
  for (const f of report.findings ?? []) {
    items.push({
      id: f.id ?? '',
      kind: 'finding',
      layer: f.layer ?? 'norms',
      severity: (f.severity as Severity) ?? 'low',
      title: f.title ?? '',
      detail: f.detail ?? '',
      paragraphId: f.anchor?.paragraph_id ?? null,
      start: f.anchor?.start ?? 0,
      finding: f,
    })
  }
  for (const r of report.revisions ?? []) {
    items.push({
      id: r.id ?? '',
      kind: 'revision',
      layer: 'norms',
      severity: 'rev',
      title: `建议修订：${clip(r.old)} 改为 ${clip(r.new)}`,
      detail: r.reason ?? '',
      paragraphId: r.anchor?.paragraph_id ?? null,
      start: r.anchor?.start ?? 0,
      revision: r,
    })
  }
  items.sort((a, b) => {
    const pa = a.paragraphId,
      pb = b.paragraphId
    if (pa === null && pb === null) return a.id.localeCompare(b.id)
    if (pa === null) return -1
    if (pb === null) return 1
    const d = (paraPos.get(pa) ?? 0) - (paraPos.get(pb) ?? 0)
    return d !== 0 ? d : a.start - b.start
  })
  return items
}

function clip(s: string | undefined, n = 24): string {
  const t = (s ?? '').replace(/\s+/g, ' ').trim()
  return t.length > n ? t.slice(0, n) + '…' : t
}

export function firstLine(detail: string): string {
  return detail.split('\n')[0] ?? ''
}

/** The item a clicked segment selects: most severe, then shortest span. */
export function pickItem(
  covering: ListItem[],
  anchorEnd: (it: ListItem) => number
): ListItem | null {
  if (!covering.length) return null
  return [...covering].sort((a, b) => {
    const d = sevRank(b.severity) - sevRank(a.severity)
    if (d) return d
    const la = a.paragraphId ? anchorEnd(a) - a.start : Infinity
    const lb = b.paragraphId ? anchorEnd(b) - b.start : Infinity
    return la - lb
  })[0]
}

/** keyboard navigation: move selection by delta, clamped. */
export function moveSelection(
  items: ListItem[],
  currentId: string | null,
  delta: number
): string | null {
  if (!items.length) return null
  const idx = items.findIndex((i) => i.id === currentId)
  if (idx === -1) return items[delta > 0 ? 0 : items.length - 1].id
  const next = Math.min(items.length - 1, Math.max(0, idx + delta))
  return items[next].id
}
