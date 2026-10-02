import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../lib/api'
import { PapersIllustration, ChevronDownIcon } from '../components/Icons'

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
    >
      <div className="flex flex-col items-center" style={{ maxWidth: 460 }}>
        {/* morphs into skeleton page 1 on drop */}
        <span style={{ viewTransitionName: 'cc-paper' }}>
          <PapersIllustration size={160} active={active} />
        </span>
        <button
          className="t26"
          style={{ fontWeight: 600, marginTop: 16 }}
          onClick={onOpenDialog}
        >
          把论文拖到这里
        </button>
        <div className="secondary" style={{ marginTop: 8 }}>
          支持英文论文的 .docx 文件。全文在本机解析，不会上传。
        </div>
        {(err || dropError) && (
          <div className="font-normal" style={{ marginTop: 12 }}>
            {err ?? dropError}
          </div>
        )}
        <div
          className="flex items-center gap-3"
          style={{ marginTop: 24 }}
        >
          <button className="pill-accent" onClick={onOpenDialog}>
            选择文件
          </button>
          <label className="pill-quiet flex items-center gap-1">
            <select
              className="font-normal"
              style={{
                appearance: 'none',
                background: 'transparent',
                border: 'none',
                padding: 0,
              }}
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
            <ChevronDownIcon size={13} color="var(--text-secondary)" />
          </label>
        </div>
      </div>
    </div>
  )
}
