import { useEffect, useState } from 'react'
import QwenIntelMorph from '../components/QwenIntelMorph'

interface ToastState {
  visible: boolean
  file?: string
  step?: string
  pct?: number
  done?: boolean
}

/** 屏幕右下角的进度弹窗（独立窗口，见主进程 ensureToast）。内容与运行页
 *  一致：真实阶段、文件名、总进度；点击回到 Clover。 */
export default function Toast({ initial }: { initial?: ToastState }) {
  const [s, setS] = useState<ToastState>(initial ?? { visible: false })
  useEffect(() => window.citecheck?.onToast?.(setS), [])
  const pct = Math.round(s.pct ?? 0)

  return (
    <div className="toast-shell">
      <button
        className="toast-card"
        onClick={() => window.citecheck?.toastClick?.()}
        aria-live="polite"
      >
        <div className="flex items-center" style={{ gap: 12 }}>
          <QwenIntelMorph width={56} />
          <div className="flex flex-col min-w-0 flex-1" style={{ textAlign: 'left' }}>
            <span className="font-semibold truncate">{s.step ?? '正在检查'}</span>
            <span className="t13 secondary truncate">{s.file ?? ''}</span>
          </div>
        </div>
        <div className="flex items-center" style={{ gap: 12, marginTop: 12 }}>
          <div
            className="run-track flex-1"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
          >
            <div
              className={`run-fill${s.done ? ' ok' : ''}`}
              style={{ transform: `scaleX(${pct / 100})` }}
            />
          </div>
          <span className="t13 secondary toast-pct">{pct}%</span>
        </div>
      </button>
    </div>
  )
}
