import { useMemo } from 'react'
import {
  anchorUnit,
  layoutSkeleton,
  MAX_PAGES,
  PAGE_H,
  PAGE_W,
  type Outline,
  type SkAnchor,
} from '../lib/outline'

interface Props {
  /** null → pre-parse shimmer placeholder */
  outline: Outline | null
  /** layer -> anchors that lit up (on each layer "done") */
  lit: Record<string, SkAnchor[]>
}

const SEV_CLASS: Record<string, string> = {
  high: 'sk-sev-high',
  medium: 'sk-sev-medium',
  low: 'sk-sev-low',
}

export default function SkeletonPaper({ outline, lit }: Props) {
  const layout = useMemo(
    () => (outline ? layoutSkeleton(outline) : null),
    [outline]
  )

  // unit key -> severity tint; page of the newest highlight for the pop
  const { litUnits, popPage } = useMemo(() => {
    const m: Record<string, string> = {}
    let pop = -1
    if (outline && layout) {
      for (const anchors of Object.values(lit)) {
        for (const a of anchors) {
          const u = anchorUnit(layout, outline, a)
          if (u) {
            m[u.key] = a.severity
            pop = u.page // last layer wins
          }
        }
      }
    }
    return { litUnits: m, popPage: pop }
  }, [outline, layout, lit])

  const litParas = useMemo(() => {
    const s = new Set<string>()
    for (const anchors of Object.values(lit))
      for (const a of anchors) s.add(a.paragraph_id)
    return s
  }, [lit])

  let stagger = 0
  const renderPage = (units: import('../lib/outline').SkPage, i: number) => (
    <div
      key={i}
      className={i === popPage ? 'sk-page sk-pop' : 'sk-page'}
      style={i === 0 ? { viewTransitionName: 'cc-paper' } : undefined}
    >
      {units.map((u) => {
        const d = Math.min(stagger++ * 8, 560)
        if (u.kind === 'heading') {
          return (
            <div key={u.key} className="sk-head" style={{ animationDelay: `${d}ms` }}>
              <span className="sk-head-title">{u.text}</span>
            </div>
          )
        }
        const sev = litUnits[u.key]
        const glow = u.paraId && litParas.has(u.paraId)
        return (
          <div
            key={u.key}
            className={`sk-bar${u.short ? ' short' : ''}${u.kind === 'ref' ? ' ref' : ''}${sev ? ` ${SEV_CLASS[sev] ?? ''}` : ''}`}
            style={{ animationDelay: `${d}ms` }}
          >
            {(u.dots ?? []).map((x, k) => (
              <i
                key={k}
                className={glow ? 'sk-dot sk-glow' : 'sk-dot'}
                style={{ left: `${x * 100}%` }}
              />
            ))}
          </div>
        )
      })}
    </div>
  )

  if (!outline || !layout) {
    // pre-parse: placeholder pages + AFFiNE-style shimmer sweep
    return (
      <div className="sk-row sk-shimmer">
        {[0, 1].map((i) => (
          <div key={i} className="sk-page">
            {Array.from({ length: 16 }).map((_, k) => (
              <div key={k} className={k % 5 === 4 ? 'sk-bar short' : 'sk-bar'} />
            ))}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="sk-row">
      {layout.pages.slice(0, MAX_PAGES).map((pg, i) => renderPage(pg, i))}
    </div>
  )
}
