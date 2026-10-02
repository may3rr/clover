import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../lib/api'

interface Props {
  benchmark: string
  setBenchmark: (b: string) => void
  onFile: (path: string) => void
  onOpenDialog: () => void
  dropError: string | null
  forceDrag?: boolean
}

interface Bench {
  id: string
  name: string
  n_papers: number
}

export default function Empty({
  benchmark,
  setBenchmark,
  onFile,
  onOpenDialog,
  dropError,
  forceDrag,
}: Props) {
  const [drag, setDrag] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [benches, setBenches] = useState<Bench[]>([])

  useEffect(() => {
    apiFetch('/benchmarks')
      .then((r) => r.json())
      .then((b: Bench[]) => setBenches(b))
      .catch(() => setBenches([]))
  }, [])

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDrag(false)
      const file = e.dataTransfer.files?.[0]
      if (!file) return
      if (!file.name.toLowerCase().endsWith('.docx')) {
        setErr('无法读取这个文件。请确认它是 .docx 格式，然后重新拖入。')
        return
      }
      setErr(null)
      onFile(window.citecheck.pathForFile(file))
    },
    [onFile]
  )

  const active = drag || forceDrag
  return (
    <div
      className="h-full flex items-center justify-center"
      style={{
        background: active ? 'var(--bg-subtle)' : 'var(--bg)',
        transition: 'background 200ms ease-out',
      }}
      onDragOver={(e) => {
        e.preventDefault()
        setDrag(true)
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={onDrop}
      data-testid="empty-screen"
      data-drag={active ? '1' : '0'}
    >
      <div className="flex flex-col items-center gap-4" style={{ maxWidth: 420 }}>
        <button
          className="font-semibold"
          style={{ fontSize: 15 }}
          onClick={onOpenDialog}
          autoFocus
        >
          把论文拖到这里
        </button>
        <div className="font-normal" style={{ fontSize: 15 }}>
          支持英文论文的 .docx 文件。全文在本机解析，不会上传。
        </div>
        {(err || dropError) && (
          <div className="font-normal" style={{ fontSize: 15 }}>
            {err ?? dropError}
          </div>
        )}
        <select
          className="pill-quiet font-normal"
          style={{ fontSize: 15, marginTop: 8 }}
          value={benchmark}
          onChange={(e) => setBenchmark(e.target.value)}
          aria-label="对标领域"
        >
          {benches.length === 0 && (
            <option value="arxiv_cs_cl">arXiv 计算语言学</option>
          )}
          {benches.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
