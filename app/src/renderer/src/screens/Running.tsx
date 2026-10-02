import { useEffect, useState } from 'react'
import { eventsUrl } from '../lib/api'

export interface LayerState {
  status: 'waiting' | 'running' | 'done' | 'failed'
  findings: number
  error?: string
}
export type LayerUI = Record<string, LayerState>

const LAYERS: { key: string; name: string }[] = [
  { key: 'authenticity', name: '文献真实性' },
  { key: 'support', name: '论断支持度' },
  { key: 'distribution', name: '引用分布' },
  { key: 'norms', name: '格式规范' },
]

interface Props {
  jobId: string
  onDone: () => void
  onFailed: (err: string) => void
  error: string | null
  onReset: () => void
  overrideLayers?: LayerUI | null
}

export default function Running({
  jobId,
  onDone,
  onFailed,
  error,
  onReset,
  overrideLayers,
}: Props) {
  const [layers, setLayers] = useState<LayerUI>(() =>
    Object.fromEntries(
      LAYERS.map((l) => [l.key, { status: 'waiting', findings: 0 }])
    )
  )

  useEffect(() => {
    if (overrideLayers) return // shots mode drives the rows directly
    let es: EventSource | null = null
    let cancelled = false
    eventsUrl(jobId).then((url) => {
      if (cancelled) return
      es = new EventSource(url)
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

  return (
    <div className="h-full flex items-center justify-center" style={{ background: 'var(--bg)' }}>
      <div className="flex flex-col gap-3" style={{ width: 360 }}>
        {LAYERS.map(({ key, name }) => {
          const s = shown[key] ?? { status: 'waiting', findings: 0 }
          return (
            <div key={key} className="flex items-center justify-between">
              <span className="font-semibold">{name}</span>
              <span className="font-normal flex items-center gap-2">
                {s.status === 'running' && (
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
                      stroke="var(--bg-subtle)"
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
                )}
                {statusLabel(s)}
              </span>
            </div>
          )
        })}
        {error && (
          <>
            <div className="font-normal" style={{ marginTop: 8 }}>
              {error}
            </div>
            <button className="pill self-center" onClick={onReset}>
              重新选择文件
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function statusLabel(s: LayerState): string {
  switch (s.status) {
    case 'waiting':
      return '等待'
    case 'running':
      return '进行中'
    case 'done':
      return s.findings > 0 ? `完成，发现 ${s.findings} 个问题` : '完成，未发现问题'
    case 'failed':
      return `未完成：${s.error ?? '未知错误'}`
  }
}
