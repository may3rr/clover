import Mascot, { type MascotStance } from './Mascot'
import { AGENT_COLOR } from '../lib/mascot'
import type { Overview, Tier } from '../types/report'

const TIER_LABEL: Record<Tier, string> = {
  below: '低于常见水平',
  near: '略低于常见水平',
  at: '达到常见水平',
  above: '高于常见水平',
  na: '无法判断',
}

/** semantic text colors only; a tier is a position, never an alarm */
function tierClass(t: Tier): string {
  if (t === 'at' || t === 'above') return 'sem-ok'
  if (t === 'near' || t === 'below') return 'sem-medium'
  return 'secondary'
}

function stanceFor(t: Tier): MascotStance {
  if (t === 'at' || t === 'above') return 'support'
  if (t === 'below') return 'doubt'
  return 'none'
}

/** Venue overview: where the manuscript sits against a few recent papers of
 *  the target venue. A quiet summary in the reading area, not a verdict. */
export default function OverviewCard({
  overview,
  style,
}: {
  overview?: Overview | null
  style?: React.CSSProperties
}) {
  if (!overview) return null

  if (overview.status === 'unavailable') {
    return (
      <div className="t13 secondary" style={style}>
        {overview.note || `这次没有生成 ${overview.venue_name} 对标。`}
      </div>
    )
  }

  const overall: Tier = overview.overall ?? 'na'
  const dims = overview.dims ?? []
  const exemplars = overview.exemplars ?? []

  return (
    <section
      aria-label={`${overview.venue_name} 对标`}
      style={{
        background: 'var(--bg-subtle)',
        borderRadius: 12,
        padding: 16,
        fontSize: 15, // the reading area is 17px; the card is interface text
        lineHeight: 1.6,
        ...style,
      }}
    >
      <div className="flex items-center" style={{ gap: 12 }}>
        <Mascot
          color={AGENT_COLOR.overview}
          size={28}
          stance={stanceFor(overall)}
        />
        <div className="font-semibold flex-1 min-w-0">
          {overview.venue_name} 对标
        </div>
        <div className={`font-semibold ${tierClass(overall)}`}>
          {TIER_LABEL[overall]}
        </div>
      </div>

      {overview.comment && (
        <div className="font-normal" style={{ marginTop: 12 }}>
          {overview.comment}
        </div>
      )}

      {dims.length > 0 && (
        <div className="flex flex-col" style={{ marginTop: 16, gap: 8 }}>
          {dims.map((d) => {
            const t: Tier = d.tier ?? 'na'
            return (
              <div key={d.key}>
                <div className="flex items-baseline justify-between" style={{ gap: 12 }}>
                  <span className="font-normal">{d.label}</span>
                  <span className={`t13 ${tierClass(t)}`}>{TIER_LABEL[t]}</span>
                </div>
                {d.note && <div className="t13 secondary">{d.note}</div>}
              </div>
            )
          })}
        </div>
      )}

      {exemplars.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="t13 secondary">对标的近期论文</div>
          <div className="flex flex-col" style={{ marginTop: 4, gap: 4 }}>
            {exemplars.map((e) => (
              <button
                key={e.id}
                className="link-accent t13"
                style={{ textAlign: 'left' }}
                onClick={() => window.citecheck.openExternal(e.url)}
              >
                {e.title}
                {e.year ? ` ${e.year}` : ''}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="t13 secondary" style={{ marginTop: 16 }}>
        这是与近期已发表论文相比的粗略位置，不是修改建议。
      </div>
    </section>
  )
}
