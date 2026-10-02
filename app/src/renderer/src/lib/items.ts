import type { Anchor, Finding, Report, Revision } from '../types/report'

export type Severity = 'high' | 'medium' | 'low' | 'rev'

export interface ListItem {
  id: string
  kind: 'finding' | 'revision' | 'group'
  /** 'norms' for revisions — they filter under 格式规范 */
  layer: string
  severity: Severity
  title: string
  detail: string
  /** every anchor this item covers (a renumber group spans the doc) */
  anchors: Anchor[]
  /** first-anchor paragraph + offset, for ordering */
  paragraphId: string | null
  start: number
  finding?: Finding
  revision?: Revision
  /** kind 'group': the collapsed reorder revisions */
  revisions?: Revision[]
}

const SEV_RANK: Record<Severity, number> = { high: 3, medium: 2, low: 1, rev: 0 }

export function sevRank(s: Severity): number {
  return SEV_RANK[s]
}

/** The inspector list: findings + revisions in document order.
 * marker_renumber / ref_reorder revisions collapse into one norms item;
 * typo revisions stay individual. Anchor-less items come first. */
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
      anchors: f.anchor ? [f.anchor] : [],
      paragraphId: f.anchor?.paragraph_id ?? null,
      start: f.anchor?.start ?? 0,
      finding: f,
    })
  }

  const reorderKinds = new Set(['marker_renumber', 'ref_reorder'])
  const reorders: Revision[] = []
  for (const r of report.revisions ?? []) {
    if (reorderKinds.has(r.kind ?? '')) {
      reorders.push(r)
      continue
    }
    items.push({
      id: r.id ?? '',
      kind: 'revision',
      layer: 'norms',
      severity: 'rev',
      title: `建议修订：${clip(r.old)} 改为 ${clip(r.new)}`,
      detail: r.reason ?? '',
      anchors: r.anchor ? [r.anchor] : [],
      paragraphId: r.anchor?.paragraph_id ?? null,
      start: r.anchor?.start ?? 0,
      revision: r,
    })
  }
  if (reorders.length) {
    const markers = reorders.filter((r) => r.kind === 'marker_renumber')
    const refs = reorders.filter((r) => r.kind === 'ref_reorder')
    const first = reorders
      .map((r) => r.anchor)
      .filter(Boolean)
      .sort(
        (a, b) =>
          (paraPos.get(a!.paragraph_id ?? '') ?? 0) -
            (paraPos.get(b!.paragraph_id ?? '') ?? 0) || a!.start - b!.start
      )[0]
    items.push({
      id: 'reorder-group',
      kind: 'group',
      layer: 'norms',
      severity: 'rev',
      title: '按首次引用顺序重排参考文献',
      detail: `涉及 ${markers.length} 处正文编号和 ${refs.length} 条参考文献，导出后以修订形式出现，可以逐条接受或拒绝。`,
      anchors: reorders.map((r) => r.anchor).filter(Boolean) as Anchor[],
      paragraphId: first?.paragraph_id ?? null,
      start: first?.start ?? 0,
      revisions: reorders,
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

/** "[1] Vaswani 等，2017，Attention is all you need" — identifies the
 * reference an authenticity/support finding is about; the issue text
 * itself lives in the detail view. */
export function refLine(item: ListItem, report: Report): string | null {
  if (item.layer !== 'authenticity' && item.layer !== 'support') return null
  const refId = item.finding?.refs?.[0]
  if (!refId) return null
  const r = (report.references ?? []).find((x) => x.id === refId)
  if (!r) return null
  const num = r.label ? `[${r.label}] ` : ''
  const first = (r.authors?.[0] ?? '').split(/[\s,]+/)[0] ?? ''
  const who = first ? `${first}${(r.authors?.length ?? 0) > 1 ? ' 等' : ''}` : ''
  const parts = [who, r.year ? String(r.year) : '', r.title ?? ''].filter(
    Boolean
  )
  return `${num}${parts.join('，')}`
}

/** The item a clicked segment selects: most severe, then shortest span. */
export function pickItem(covering: ListItem[]): ListItem | null {
  if (!covering.length) return null
  const span = (i: ListItem) =>
    i.anchors.length
      ? Math.min(...i.anchors.map((a) => (a.end ?? 0) - (a.start ?? 0)))
      : Infinity
  return [...covering].sort((a, b) => {
    const d = sevRank(b.severity) - sevRank(a.severity)
    return d !== 0 ? d : span(a) - span(b)
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
