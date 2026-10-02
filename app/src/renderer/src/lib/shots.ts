import type { Report } from '../types/report'
import type { LayerUI } from '../screens/Running'
import { buildItems } from './items'

export interface ShotCtx {
  report?: Report
  setScreen?: (s: 'empty' | 'running' | 'report' | 'error') => void
  setReport?: (r: Report | null) => void
  setLayers?: (l: LayerUI) => void
  selectItem?: (id: string | null, open?: boolean) => void
  setDrag?: (v: boolean) => void
}

/** Debug-only state driver for `npm run shots` (CITECHECK_SHOTS). */
export function applyShotState(state: string, ctx: ShotCtx) {
  const report = ctx.report
  ctx.setDrag?.(false)
  ctx.selectItem?.(null)

  const items = report ? buildItems(report) : []
  const firstOf = (pred: (i: (typeof items)[0]) => boolean) =>
    items.find(pred)?.id ?? null

  switch (state) {
    case 'empty':
      ctx.setScreen?.('empty')
      return
    case 'empty-dragover':
      ctx.setScreen?.('empty')
      ctx.setDrag?.(true)
      return
    case 'running':
      ctx.setScreen?.('running')
      ctx.setLayers?.({
        authenticity: { status: 'done', findings: 3 },
        support: { status: 'running', findings: 0 },
        distribution: { status: 'done', findings: 7 },
        norms: { status: 'waiting', findings: 0 },
      })
      return
    case 'report':
      ctx.setReport?.(report ?? null)
      ctx.setScreen?.('report')
      return
    case 'report-selected': {
      ctx.setReport?.(report ?? null)
      ctx.setScreen?.('report')
      const id =
        firstOf((i) => i.severity === 'high') ??
        firstOf((i) => i.severity === 'medium') ??
        items[0]?.id ??
        null
      ctx.selectItem?.(id, false) // selected in list + paper, detail closed
      return
    }
    case 'detail-support':
    case 'detail-authenticity':
    case 'detail-distribution':
    case 'detail-norms': {
      ctx.setReport?.(report ?? null)
      ctx.setScreen?.('report')
      const layer = state.replace('detail-', '')
      const id =
        firstOf((i) => i.kind === 'finding' && i.layer === layer) ??
        // the sample report has no norms finding — a revision row is the
        // same norms surface
        (layer === 'norms' ? firstOf((i) => i.kind === 'revision') : null)
      ctx.selectItem?.(id)
      return
    }
    case 'detail-revision': {
      ctx.setReport?.(report ?? null)
      ctx.setScreen?.('report')
      ctx.selectItem?.(firstOf((i) => i.kind === 'revision'))
      return
    }
  }
}
