import { useEffect, useState } from 'react'
import { DocTextFillIcon } from './Icons'

const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

type Kind = 'docx' | 'other'

/** what is being dragged, as far as the browser tells before the drop */
function kindOf(dt: DataTransfer | null): Kind | null {
  if (!dt || !Array.from(dt.types).includes('Files')) return null
  const item = dt.items?.[0]
  // macOS reports the docx MIME; an empty type means "unknown" — let the
  // drop decide by file name rather than rejecting a valid paper
  return !item || !item.type || item.type === DOCX_MIME ? 'docx' : 'other'
}

/** Whole-window drop target for the screens that have no drop zone of their
 *  own (report, settings): dragging a paper anywhere answers at once, and
 *  dropping it starts a new check. Home keeps its own in-place drop zone. */
export default function DropOverlay({
  enabled,
  force,
  onFile,
}: {
  enabled: boolean
  /** screenshot mode: show the docx state without a real drag */
  force?: boolean
  onFile: (path: string) => void
}) {
  const [kind, setKind] = useState<Kind | null>(null)

  useEffect(() => {
    if (!enabled) {
      setKind(null)
      return
    }
    // dragenter/leave fire for every child crossed; count to know when the
    // pointer really left the window
    let depth = 0
    const enter = (e: DragEvent) => {
      const k = kindOf(e.dataTransfer)
      if (!k) return
      depth++
      setKind(k)
    }
    const over = (e: DragEvent) => {
      if (kindOf(e.dataTransfer)) e.preventDefault()
    }
    const leave = () => {
      depth = Math.max(0, depth - 1)
      if (depth === 0) setKind(null)
    }
    const drop = (e: DragEvent) => {
      e.preventDefault()
      depth = 0
      setKind(null)
      const file = e.dataTransfer?.files?.[0]
      if (file && file.name.toLowerCase().endsWith('.docx'))
        onFile(window.citecheck.pathForFile(file))
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [enabled, onFile])

  const shown = kind ?? (force ? 'docx' : null)
  if (!shown) return null
  return (
    <div className="drop-overlay" aria-live="polite">
      <div className="drop-card">
        <span style={{ color: shown === 'docx' ? 'var(--accent)' : 'var(--text-secondary)' }}>
          <DocTextFillIcon size={32} />
        </span>
        <div className="font-semibold" style={{ fontSize: 17 }}>
          {shown === 'docx' ? '松开开始体检' : '只能检查 .docx 文件'}
        </div>
        <div className="t13 secondary">
          {shown === 'docx'
            ? '当前报告已保存，可以在侧栏的最近检查里找回。'
            : '请在 Word 中另存为 .docx，然后重新拖入。'}
        </div>
      </div>
    </div>
  )
}
