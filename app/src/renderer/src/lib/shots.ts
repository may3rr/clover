import type { Report } from '../types/report'
import type { LayerUI } from '../screens/Running'
import { buildItems } from './items'
import {
  anchorsFromReport,
  outlineFromReport,
  type Outline,
  type SkAnchor,
} from './outline'

export interface ShotCtx {
  report?: Report
  setScreen?: (
    s: 'empty' | 'running' | 'report' | 'error' | 'settings' | 'onboarding'
  ) => void
  setReport?: (r: Report | null) => void
  setLayers?: (l: LayerUI) => void
  setOutline?: (o: Outline | null) => void
  setAnchors?: (a: Record<string, SkAnchor[]>) => void
  selectItem?: (id: string | null, open?: boolean) => void
  setFilter?: (layer: string | null) => void
  setDrag?: (v: boolean) => void
  setPrefs?: (p: import('./prefs').Prefs) => void
  setOnboardStep?: (n: 0 | 1 | 2 | 3) => void
  setCredits?: (on: boolean) => void
  setSettingsSection?: (s: 'account' | 'comments' | 'model' | 'usage' | 'about') => void
}

const SAMPLE_PREFS = {
  name: '李明',
  avatar: { kind: 'color' as const, color: 'teal', image: null },
  comment_author: '',
  comment_initials: '',
  onboarded: true,
}

const LAYER_KEYS = ['authenticity', 'support', 'distribution', 'norms']

// per-layer finding counts, so the running page agrees with the report
function layerCounts(report?: Report): Record<string, number> {
  const n: Record<string, number> = {}
  for (const k of LAYER_KEYS) n[k] = 0
  for (const f of report?.findings ?? []) n[f.layer] = (n[f.layer] ?? 0) + 1
  return n
}

/** Debug-only state driver for `npm run shots` (CITECHECK_SHOTS). */
export function applyShotState(state: string, ctx: ShotCtx) {
  const report = ctx.report
  ctx.setDrag?.(false)
  ctx.selectItem?.(null)
  ctx.setFilter?.(null)
  ctx.setPrefs?.(SAMPLE_PREFS)
  ctx.setCredits?.(false)

  const items = report ? buildItems(report) : []
  const firstOf = (pred: (i: (typeof items)[0]) => boolean) =>
    items.find(pred)?.id ?? null
  const outline = report ? outlineFromReport(report) : null
  const anchors = report ? anchorsFromReport(report) : {}
  const counts = layerCounts(report)
  const done = (k: string) => ({ status: 'done' as const, findings: counts[k] })
  const ALL_DONE: LayerUI = Object.fromEntries(LAYER_KEYS.map((k) => [k, done(k)]))

  // item:<id> — report with that inspector item's detail open (the web
  // replica on the landing page points each section at one finding)
  if (state.startsWith('item:')) {
    ctx.setReport?.(report ?? null)
    ctx.setScreen?.('report')
    ctx.selectItem?.(state.slice(5))
    return
  }

  switch (state) {
    case 'onboarding-intro':
    case 'onboarding-model':
    case 'onboarding-profile':
    case 'onboarding-privacy': {
      const steps = ['intro', 'model', 'profile', 'privacy']
      ctx.setOnboardStep?.(steps.indexOf(state.replace('onboarding-', '')) as 0 | 1 | 2 | 3)
      ctx.setScreen?.('onboarding')
      return
    }
    case 'credits':
      ctx.setSettingsSection?.('about')
      ctx.setScreen?.('settings')
      ctx.setCredits?.(true)
      return
    case 'empty':
      ctx.setScreen?.('empty')
      return
    case 'empty-dragover':
      ctx.setScreen?.('empty')
      ctx.setDrag?.(true)
      return
    case 'running-shimmer':
      // before "parsed" — placeholder pages + wave
      ctx.setScreen?.('running')
      ctx.setOutline?.(null)
      ctx.setAnchors?.({})
      ctx.setLayers?.({
        authenticity: { status: 'running', findings: 0 },
        support: { status: 'waiting', findings: 0 },
        distribution: { status: 'waiting', findings: 0 },
        norms: { status: 'waiting', findings: 0 },
      })
      return
    case 'running':
    case 'running-mid':
      ctx.setScreen?.('running')
      ctx.setOutline?.(outline)
      // two layers landed — their anchors are already lit
      ctx.setAnchors?.({
        authenticity: anchors['authenticity'] ?? [],
        distribution: anchors['distribution'] ?? [],
      })
      ctx.setLayers?.({
        authenticity: done('authenticity'),
        support: { status: 'running', findings: 0 },
        distribution: done('distribution'),
        norms: { status: 'waiting', findings: 0 },
      })
      return
    case 'running-done':
      ctx.setScreen?.('running')
      ctx.setOutline?.(outline)
      ctx.setAnchors?.(anchors)
      ctx.setLayers?.(ALL_DONE)
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
    case 'report-filter-support': {
      ctx.setReport?.(report ?? null)
      ctx.setScreen?.('report')
      ctx.setFilter?.('support')
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
        // the sample report has no norms finding — the collapsed reorder
        // group is the same norms surface
        (layer === 'norms' ? firstOf((i) => i.id === 'reorder-group') : null)
      ctx.selectItem?.(id)
      return
    }
    case 'detail-revision': {
      ctx.setReport?.(report ?? null)
      ctx.setScreen?.('report')
      // no individual typo revisions in the sample — the collapsed
      // reorder group carries the revision detail UI
      ctx.selectItem?.(
        firstOf((i) => i.kind === 'revision') ??
          firstOf((i) => i.id === 'reorder-group')
      )
      return
    }
    case 'settings-account':
    case 'settings-comments':
    case 'settings-model':
    case 'settings-usage':
    case 'settings-about': {
      ctx.setSettingsSection?.(
        state.replace('settings-', '') as
          | 'account' | 'comments' | 'model' | 'usage' | 'about'
      )
      ctx.setScreen?.('settings')
      return
    }
  }
}
