import { useEffect, useRef, useState } from 'react'
import { eventsUrl } from '../lib/api'
import {
  CheckCircleFillIcon,
  ExclaimCircleFillIcon,
} from '../components/Icons'
import Mascot, { type MascotState } from '../components/Mascot'
import { AGENT_COLOR } from '../lib/mascot'
import SkeletonPaper from '../components/Skeleton'
import type { Outline, SkAnchor } from '../lib/outline'

export interface LayerState {
  status: 'waiting' | 'running' | 'done' | 'failed'
  findings: number
  error?: string
}
export type LayerUI = Record<string, LayerState>
/** venue overview stage, driven by the SSE `overview` event */
export type OverviewRun = 'waiting' | 'running' | 'ok' | 'unavailable'

const LAYERS: { key: string; name: string }[] = [
  { key: 'authenticity', name: '文献真实性' },
  { key: 'support', name: '论断支持度' },
  { key: 'distribution', name: '引用分布' },
  { key: 'norms', name: '格式规范' },
]
const OVERVIEW_NAME = '期刊评审'

interface Props {
  jobId: string
  fileName: string
  onDone: () => void
  onFailed: (err: string) => void
  error: string | null
  onReset: () => void
  /** target venue id; '' = overview stage off, so its row is hidden */
  venue?: string
  /** shots mode: drive the rows and skeleton directly */
  overrideLayers?: LayerUI | null
  overrideOutline?: Outline | null
  overrideAnchors?: Record<string, SkAnchor[]> | null
  /** shots mode: show the overview row in this state (omit to hide it) */
  overrideOverview?: OverviewRun | null
}

export default function Running({
  jobId,
  fileName,
  onDone,
  onFailed,
  error,
  onReset,
  venue,
  overrideLayers,
  overrideOutline,
  overrideAnchors,
  overrideOverview,
}: Props) {
  const [layers, setLayers] = useState<LayerUI>(() =>
    Object.fromEntries(
      LAYERS.map((l) => [l.key, { status: 'waiting', findings: 0 }])
    )
  )
  const [overview, setOverview] = useState<OverviewRun>('waiting')
  const [outline, setOutline] = useState<Outline | null>(null)
  const [anchors, setAnchors] = useState<Record<string, SkAnchor[]>>({})

  useEffect(() => {
    if (overrideLayers) return // shots mode drives the rows directly
    let es: EventSource | null = null
    let cancelled = false
    eventsUrl(jobId).then((url) => {
      if (cancelled) return
      es = new EventSource(url)
      es.addEventListener('parsed', (ev) => {
        const d = JSON.parse((ev as MessageEvent).data)
        setOutline(d.outline ?? null)
      })
      es.addEventListener('layer', (ev) => {
        const d = JSON.parse((ev as MessageEvent).data)
        setLayers((prev) => ({
          ...prev,
          [d.layer]: {
            status: d.status,
            findings: d.findings ?? 0,
            error: d.error,
          },
        }))
        if (d.anchors?.length) {
          setAnchors((prev) => ({
            ...prev,
            [d.layer]: [...(prev[d.layer] ?? []), ...d.anchors],
          }))
        }
      })
      es.addEventListener('overview', (ev) => {
        const d = JSON.parse((ev as MessageEvent).data)
        if (
          d.status === 'running' ||
          d.status === 'ok' ||
          d.status === 'unavailable'
        )
          setOverview(d.status)
      })
      es.addEventListener('done', () => {
        es?.close()
        onDone()
      })
      es.addEventListener('failed', (ev) => {
        es?.close()
        const d = JSON.parse((ev as MessageEvent).data)
        onFailed(d.error ?? '体检失败。请重试。')
      })
      es.onerror = () => {
        es?.close()
        onFailed('连接中断。请重新体检。')
      }
    })
    return () => {
      cancelled = true
      es?.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  const shown = overrideLayers ?? layers
  const skOutline = overrideLayers ? (overrideOutline ?? null) : outline
  const skAnchors = overrideLayers ? (overrideAnchors ?? {}) : anchors
  const ovStatus: OverviewRun | null = overrideLayers
    ? (overrideOverview ?? null)
    : venue
      ? overview
      : null

  return (
    <div
      className="relative h-full flex flex-col items-center justify-center"
      style={{ background: 'var(--bg)' }}
    >
      <div
        className="drag-strip"
        style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 52 }}
      />
      <div className="t26 font-semibold">{fileName}</div>
      <div className="secondary" style={{ marginTop: 8 }}>
        正在检查，通常需要一两分钟。
      </div>
      <div
        className="flex items-start"
        style={{ gap: 32, marginTop: 32 }}
      >
        {/* document skeleton: page thumbnails light up as layers land */}
        <div style={{ paddingTop: 8 }}>
          <SkeletonPaper outline={skOutline} lit={skAnchors} />
        </div>
        <div
          className="flex flex-col run-panel"
          style={{
            width: 380,
            background: 'var(--bg-subtle)',
            borderRadius: 12,
            padding: '4px 16px',
            viewTransitionName: 'cc-panel',
          }}
        >
          {LAYERS.map(({ key, name }) => {
            const s = shown[key] ?? { status: 'waiting', findings: 0 }
            return (
              <div
                key={key}
                className="flex items-center justify-between"
                style={{ height: 44 }}
              >
                <span
                  className="flex items-center"
                  style={{ fontWeight: 500, gap: 12 }}
                >
                  <RunMascot agent={key} status={s.status} />
                  {name}
                </span>
                <span className="secondary flex items-center gap-2">
                  <StatusMark s={s} />
                  <StatusLabel s={s} />
                </span>
              </div>
            )
          })}
          {ovStatus && (
            <div
              className="flex items-center justify-between"
              style={{ height: 44 }}
            >
              <span
                className="flex items-center"
                style={{ fontWeight: 500, gap: 12 }}
              >
                <RunMascot
                  agent="overview"
                  status={
                    ovStatus === 'ok' || ovStatus === 'unavailable'
                      ? 'done'
                      : ovStatus
                  }
                />
                {OVERVIEW_NAME}
              </span>
              <span className="secondary flex items-center gap-2">
                <StatusMark
                  s={{
                    status:
                      ovStatus === 'ok'
                        ? 'done'
                        : ovStatus === 'running'
                          ? 'running'
                          : 'waiting',
                    findings: 0,
                  }}
                />
                {{
                  waiting: '等待',
                  running: '进行中',
                  ok: '已完成',
                  unavailable: '暂无对标',
                }[ovStatus]}
              </span>
            </div>
          )}
        </div>
      </div>
      {error && (
        <div
          className="flex flex-col items-center gap-3"
          style={{ marginTop: 16 }}
        >
          <div className="font-normal">{error}</div>
          <button className="pill" onClick={onReset}>
            重新选择文件
          </button>
        </div>
      )}
    </div>
  )
}

/** the layer's agent: sleeps until its turn, reads and thinks while it
 *  works, nods once when it lands, worries when it fails */
function RunMascot({
  agent,
  status,
}: {
  agent: string
  status: LayerState['status']
}) {
  const [phase, setPhase] = useState<MascotState>('reading')
  useEffect(() => {
    if (status !== 'running') return
    setPhase('reading')
    const iv = setInterval(
      () => setPhase((p) => (p === 'reading' ? 'thinking' : 'reading')),
      3200
    )
    return () => clearInterval(iv)
  }, [status])
  const state: MascotState =
    status === 'running'
      ? phase
      : status === 'failed'
        ? 'worried'
        : status === 'done'
          ? 'idle'
          : 'sleep'
  return (
    <Mascot
      color={AGENT_COLOR[agent]}
      size={24}
      state={state}
      cue={status === 'done' ? { action: 'nod', key: 'done' } : null}
      style={{
        opacity: status === 'waiting' ? 0.5 : 1,
        transition: 'opacity 240ms var(--ease)',
      }}
    />
  )
}

function StatusMark({ s }: { s: LayerState }) {
  if (s.status === 'running') {
    return (
      <svg
        className="spinner"
        width="14"
        height="14"
        viewBox="0 0 14 14"
        aria-hidden
      >
        <circle
          cx="7"
          cy="7"
          r="5.5"
          fill="none"
          stroke="var(--fill-strong)"
          strokeWidth="2"
        />
        <path
          d="M 7 1.5 A 5.5 5.5 0 0 1 12.5 7"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    )
  }
  if (s.status === 'done')
    return <CheckCircleFillIcon size={14} draw />
  if (s.status === 'failed') return <ExclaimCircleFillIcon size={14} />
  return null
}

/** finding count ticks up from 0 over ≤400ms when a layer lands */
function useCountUp(target: number, active: boolean): number {
  const [n, setN] = useState(0)
  const shown = useRef(0)
  useEffect(() => {
    if (!active) {
      shown.current = 0
      setN(0)
      return
    }
    const from = shown.current
    if (from >= target) {
      setN(target)
      shown.current = target
      return
    }
    const steps = Math.max(1, Math.min(target - from, 10))
    const iv = setInterval(() => {
      shown.current = Math.min(
        target,
        shown.current + Math.ceil((target - from) / steps)
      )
      setN(shown.current)
      if (shown.current >= target) clearInterval(iv)
    }, 40)
    return () => clearInterval(iv)
  }, [target, active])
  return n
}

function StatusLabel({ s }: { s: LayerState }) {
  const count = useCountUp(s.findings, s.status === 'done')
  switch (s.status) {
    case 'waiting':
      return <>等待</>
    case 'running':
      return <>进行中</>
    case 'done':
      return <>{count > 0 ? `${count} 个问题` : '未发现问题'}</>
    case 'failed':
      return <>{s.error ?? '未完成'}</>
  }
}
