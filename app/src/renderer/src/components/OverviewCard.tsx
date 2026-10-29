import { useEffect, useRef, useState } from 'react'
import Mascot, { type MascotStance } from './Mascot'
import OrbitDots from './OrbitDots'
import { AGENT_COLOR } from '../lib/mascot'
import { exemplarName } from '../lib/venue'
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

const DIM_LABELS = [
  '实验规模',
  '分析深度',
  '文献覆盖',
  '引用可靠性',
  '结构完整',
]
/** 占位延迟 200ms 出现；出现后至少停留 400ms，再换成结果 */
const PLACEHOLDER_DELAY_MS = 200
const PLACEHOLDER_MIN_MS = 400

/** Venue overview: where the manuscript sits against a few recent papers of
 *  the target venue. A quiet summary in the reading area, not a verdict.
 *
 *  报告先开、对标后到：overview 为 pending 时显示与最终卡片同形的占位，
 *  结果到达后原地换入。占位只写已经确定的信息（刊名、五个维度的名称），
 *  不做假进度。 */
export default function OverviewCard({
  overview,
  style,
}: {
  overview?: Overview | null
  style?: React.CSSProperties
}) {
  const mountedAt = useRef(performance.now())
  const [held, setHeld] = useState<Overview | null | undefined>(overview)
  const wasPending = useRef(overview?.status === 'pending')

  useEffect(() => {
    if (overview?.status === 'pending') {
      wasPending.current = true
      setHeld(overview)
      return
    }
    if (held?.status !== 'pending') {
      setHeld(overview)
      return
    }
    // 对标失败（后端给 null）：占位换成一行说明，不让卡片无声消失
    const next: Overview | null | undefined = overview ?? {
      ...held,
      status: 'unavailable',
      note: `这次没有生成 ${held.venue_name} 对标。`,
    }
    const wait = Math.max(
      0,
      PLACEHOLDER_DELAY_MS + PLACEHOLDER_MIN_MS - (performance.now() - mountedAt.current)
    )
    const t = setTimeout(() => setHeld(next), wait)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overview])

  if (!held) return null
  if (held.status === 'pending') {
    return <PendingCard venueName={held.venue_name} style={style} />
  }
  return (
    <ResultCard
      overview={held}
      settling={wasPending.current}
      style={style}
    />
  )
}

function PlaceholderLine({
  height = 24,
  bar = 12,
  width = '100%',
}: {
  height?: number
  bar?: number
  width?: string
}) {
  return (
    <div className="flex items-center" style={{ height }}>
      <div className="ov-ph" style={{ height: bar, width }} />
    </div>
  )
}

/** 与最终卡片同形：标题行、三行评语、五个维度、对标论文、说明 */
function PendingCard({
  venueName,
  style,
}: {
  venueName: string
  style?: React.CSSProperties
}) {
  return (
    <section
      className="overview-card ov-pending"
      aria-label={`${venueName} 对标`}
      aria-busy="true"
      style={{
        background: 'var(--bg-subtle)',
        padding: 16,
        fontSize: 15,
        lineHeight: 1.6,
        ...style,
      }}
    >
      <div className="flex items-center" style={{ gap: 12 }}>
        <span
          className="flex items-center justify-center"
          style={{ width: 28, height: 28, flex: 'none' }}
        >
          <OrbitDots size={28} color={AGENT_COLOR.overview} />
        </span>
        <div className="font-semibold flex-1 min-w-0">{venueName} 对标</div>
        <div className="font-semibold secondary">正在评审</div>
      </div>
      <div style={{ marginTop: 12 }}>
        <PlaceholderLine />
        <PlaceholderLine />
        <PlaceholderLine width="60%" />
      </div>
      <div className="flex flex-col" style={{ marginTop: 16, gap: 8 }}>
        {DIM_LABELS.map((label) => (
          <div key={label}>
            <div className="flex items-baseline justify-between" style={{ gap: 12 }}>
              <span className="font-normal">{label}</span>
              <div className="ov-ph" style={{ height: 12, width: 72 }} />
            </div>
            <PlaceholderLine height={18} bar={10} width="70%" />
          </div>
        ))}
      </div>
      <div style={{ marginTop: 16 }}>
        <div className="t13 secondary">对标的论文</div>
        <div style={{ marginTop: 4 }}>
          <PlaceholderLine height={18} bar={10} width="80%" />
          <PlaceholderLine height={18} bar={10} width="72%" />
          <PlaceholderLine height={18} bar={10} width="76%" />
        </div>
      </div>
      <div className="t13 secondary" style={{ marginTop: 16 }}>
        这是与该刊已发表论文相比的粗略位置，不是修改建议。
      </div>
    </section>
  )
}

function ResultCard({
  overview,
  settling,
  style,
}: {
  overview: Overview
  /** 从占位换入：三点收拢成小球，档次和评语落定 */
  settling: boolean
  style?: React.CSSProperties
}) {
  const [iconReady, setIconReady] = useState(!settling)
  useEffect(() => {
    if (iconReady) return
    // 收拢动画在离屏时不会走完，兜底
    const t = setTimeout(() => setIconReady(true), 400)
    return () => clearTimeout(t)
  }, [iconReady])

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
      className="overview-card"
      aria-label={`${overview.venue_name} 对标`}
      style={{
        background: 'var(--bg-subtle)',
        padding: 16,
        fontSize: 15, // the reading area is 17px; the card is interface text
        lineHeight: 1.6,
        ...style,
      }}
    >
      <div className="flex items-center" style={{ gap: 12 }}>
        {iconReady ? (
          <span className={settling ? 'ov-pop' : undefined} style={{ display: 'flex' }}>
            <Mascot
              color={AGENT_COLOR.overview}
              size={28}
              stance={stanceFor(overall)}
            />
          </span>
        ) : (
          <span
            className="flex items-center justify-center"
            style={{ width: 28, height: 28, flex: 'none' }}
          >
            <OrbitDots
              size={28}
              color={AGENT_COLOR.overview}
              collapsed
              onCollapsed={() => setIconReady(true)}
            />
          </span>
        )}
        <div className="font-semibold flex-1 min-w-0">
          {overview.venue_name} 对标
        </div>
        <div className={`font-semibold ${tierClass(overall)}${settling ? ' ov-tier' : ''}`}>
          {TIER_LABEL[overall]}
        </div>
      </div>

      {overview.comment && (
        <div
          className={`font-normal${settling ? ' ov-in' : ''}`}
          style={{ marginTop: 12 }}
        >
          {overview.comment}
        </div>
      )}

      {dims.length > 0 && (
        <div className="flex flex-col" style={{ marginTop: 16, gap: 8 }}>
          {dims.map((d, idx) => {
            const t: Tier = d.tier ?? 'na'
            return (
              <div
                key={d.key}
                className={settling ? 'ov-in' : undefined}
                style={settling ? { animationDelay: `${120 + idx * 40}ms` } : undefined}
              >
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
          <div className="t13 secondary">对标的论文</div>
          <div className="flex flex-col" style={{ marginTop: 4, gap: 4 }}>
            {exemplars.map((e) => {
              const text = `${exemplarName(e)}${e.year ? `，${e.year}` : ''}`
              const url = e.url
              return url ? (
                <button
                  key={e.id}
                  className="link-accent t13"
                  style={{ textAlign: 'left' }}
                  onClick={() => window.citecheck.openExternal(url)}
                >
                  {text}
                </button>
              ) : (
                <div key={e.id} className="t13">
                  {text}
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="t13 secondary" style={{ marginTop: 16 }}>
        这是与该刊已发表论文相比的粗略位置，不是修改建议。
      </div>
    </section>
  )
}
