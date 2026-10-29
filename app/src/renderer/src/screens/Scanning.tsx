import { useEffect, useState } from 'react'
import { apiFetch } from '../lib/api'
import OrbitDots from '../components/OrbitDots'

interface Progress {
  stage: string
  done: number
  total: number
}

const STAGE_TEXT: Record<string, string> = {
  reading: '正在读取论文',
  pdfs: '正在读取文献 PDF',
  link: '正在匹配参考文献',
  ask: '正在请模型确认相近的候选',
  venue: '正在判断范文所属期刊',
  done: '正在打开连接确认页',
}

/** 拖入文件夹后立刻出现：读 PDF、匹配参考文献、必要时问模型，可能要几十秒。
 *  每 400ms 向后端取一次真实阶段，不做假进度。 */
export default function Scanning({
  scanId,
  name,
  onCancel,
}: {
  scanId: string
  name: string
  onCancel: () => void
}) {
  const [p, setP] = useState<Progress>({ stage: 'reading', done: 0, total: 0 })

  useEffect(() => {
    let live = true
    const tick = async () => {
      try {
        const r = await apiFetch(`/library/scan/${scanId}`)
        if (live && r.ok) setP((await r.json()) as Progress)
      } catch {
        /* 下一次再取 */
      }
    }
    const iv = setInterval(tick, 400)
    return () => {
      live = false
      clearInterval(iv)
    }
  }, [scanId])

  const counted = p.total > 0
  const frac = counted ? Math.min(1, p.done / p.total) : 0
  return (
    <div
      className="relative h-full flex flex-col items-center justify-center"
      style={{ background: 'var(--bg)' }}
    >
      <div
        className="drag-strip"
        style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 52 }}
      />
      <div className="flex flex-col items-center rise-in" style={{ width: 360 }}>
        <OrbitDots size={28} color="var(--accent)" />
        <div className="t26 font-semibold" style={{ marginTop: 24 }}>
          正在扫描文献文件夹
        </div>
        <div
          className="secondary truncate"
          style={{ marginTop: 8, maxWidth: '100%' }}
        >
          {name}
        </div>
        <div style={{ marginTop: 24, width: '100%' }}>
          <div className="flex items-center justify-between t13 secondary">
            <span className="truncate">{STAGE_TEXT[p.stage] ?? '正在扫描'}</span>
            {counted && (
              <span style={{ marginLeft: 12 }}>
                {p.done} / {p.total}
              </span>
            )}
          </div>
          <div
            className={`run-track thin${counted ? '' : ' stalled'}`}
            style={{ marginTop: 8 }}
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={p.total || 100}
            aria-valuenow={p.done}
          >
            <div
              className="run-fill"
              style={{ transform: `scaleX(${counted ? frac : 0.03})` }}
            />
          </div>
        </div>
        <button className="pill-quiet" style={{ marginTop: 24 }} onClick={onCancel}>
          取消
        </button>
      </div>
    </div>
  )
}
