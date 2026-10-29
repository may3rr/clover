import { useCallback, useEffect, useRef, useState } from 'react'

/** Where the export went, and the two things people do next: open it, or
 *  find it. Stays until dismissed (click outside, Esc, or an action). */
export default function ExportDone({
  path,
  tex,
  onClose,
}: {
  path: string
  tex: boolean
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [err, setErr] = useState<string | null>(null)
  // 进入走弹簧，退出 140ms；用 transition，快速连点时从当前状态折返
  const [shown, setShown] = useState(false)
  const leaveTimer = useRef<number>()
  useEffect(() => {
    const r = requestAnimationFrame(() => setShown(true))
    return () => {
      cancelAnimationFrame(r)
      window.clearTimeout(leaveTimer.current)
    }
  }, [])
  const dismiss = useCallback(() => {
    setShown(false)
    window.clearTimeout(leaveTimer.current)
    leaveTimer.current = window.setTimeout(onClose, 140)
  }, [onClose])
  const parts = path.split('/')
  const name = parts.pop() ?? path
  const folder = parts.pop() ?? ''

  useEffect(() => {
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) dismiss()
    }
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dismiss()
    }
    // next tick: the click that opened the popover must not close it
    const t = setTimeout(() => {
      window.addEventListener('mousedown', down)
      window.addEventListener('keydown', key)
    }, 0)
    return () => {
      clearTimeout(t)
      window.removeEventListener('mousedown', down)
      window.removeEventListener('keydown', key)
    }
  }, [dismiss])

  const open = async () => {
    const e = await window.citecheck.openPath(path)
    if (e) setErr(e)
    else dismiss()
  }
  const reveal = () => {
    window.citecheck.revealInFinder(path)
    dismiss()
  }

  return (
    <div
      ref={ref}
      className={`export-pop${shown ? ' in' : ''}`}
      role="dialog"       aria-label="导出完成"
    >
      <div className="font-semibold">已导出</div>
      <div className="export-pop-name">{name}</div>
      <div className="t13 secondary">
        {folder ? `保存在 ${folder} 文件夹` : '已保存'}
        {tex ? '，批注写在源码注释里，修订在 clover-revisions.patch' : ''}
      </div>
      {err && <div className="t13 sem-high">{err}</div>}
      <div className="flex items-center gap-2" style={{ marginTop: 4 }}>
        {tex ? (
          <>
            <button className="pill-accent" onClick={reveal}>
              在访达中显示
            </button>
            <button className="pill-quiet" onClick={open}>
              解压到同一文件夹
            </button>
          </>
        ) : (
          <>
            <button className="pill-accent" onClick={open}>
              打开文件
            </button>
            <button className="pill-quiet" onClick={reveal}>
              在访达中显示
            </button>
          </>
        )}
      </div>
    </div>
  )
}
