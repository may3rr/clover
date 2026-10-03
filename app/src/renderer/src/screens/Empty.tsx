import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../lib/api'
import {
  PapersIllustration,
  ChevronDownIcon,
  LayerTile,
} from '../components/Icons'
import AccountChip from '../components/AccountChip'
import HistoryRow from '../components/HistoryRow'
import { useReports } from '../lib/useReports'
import type { Prefs } from '../lib/prefs'

interface Props {
  benchmark: string
  setBenchmark: (b: string) => void
  onFile: (path: string) => void
  onOpenDialog: () => void
  onOpenReport: (id: string) => void
  dropError: string | null
  forceDrag?: boolean
  prefs: Prefs
  onOpenSettings: () => void
}

interface Bench {
  id: string
  name: string
  n_papers: number
}

/** Home: the three-pane shell with history in the sidebar and the drop
 *  zone as the reading area — the window never shows a bare whiteboard. */
const PREVIEW_LAYERS: [string, string][] = [
  ['authenticity', '文献真实性'],
  ['support', '论断支持度'],
  ['distribution', '引用分布'],
  ['norms', '格式规范'],
]

export default function Empty({
  benchmark,
  setBenchmark,
  onFile,
  onOpenDialog,
  onOpenReport,
  dropError,
  forceDrag,
  prefs,
  onOpenSettings,
}: Props) {
  const [drag, setDrag] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [benches, setBenches] = useState<Bench[]>([])
  const { reports, remove } = useReports()

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
      className="relative h-full overflow-hidden"
      onDragOver={(e) => {
        e.preventDefault()
        setDrag(true)
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={onDrop}
    >
      {/* ---------- sidebar: history ---------- */}
      <aside className="glass-sidebar flex flex-col">
        <div className="drag-strip" style={{ height: 52, flex: 'none' }} />
        <div className="group-label" style={{ fontWeight: 600 }}>
          最近检查
        </div>
        <nav
          className="flex-1 overflow-y-auto flex flex-col gap-1"
          style={{ padding: '0 8px 8px' }}
        >
          {reports.length === 0 && (
            <div className="t13 secondary" style={{ padding: '4px 12px' }}>
              检查过的论文会出现在这里
            </div>
          )}
          {reports.map((h) => (
            <HistoryRow
              key={h.id}
              meta={h}
              onOpen={() => onOpenReport(h.id)}
              onDelete={() => remove(h.id)}
            />
          ))}
        </nav>
        <div style={{ padding: '0 12px 12px' }}>
          <AccountChip prefs={prefs} onOpen={onOpenSettings} />
        </div>
      </aside>

      {/* ---------- center: drop zone ---------- */}
      <div
        className="flex flex-col h-full"
        style={{
          marginLeft: 240,
          marginRight: 380,
          background: active ? 'var(--bg-subtle)' : 'var(--bg)',
          transition: 'background 200ms ease-out',
        }}
      >
        <div
          className={active ? undefined : 'drag-strip'}
          style={{ height: 52, flex: 'none' }}
        />
        <main className="paper flex-1 overflow-y-auto flex items-center justify-center">
          <div
            className="flex flex-col items-center"
            style={{ maxWidth: 460, paddingBottom: 48 }}
          >
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
        </main>
      </div>

      {/* ---------- inspector: empty placeholder ---------- */}
      <aside className="inspector">
        <div
          className={active ? undefined : 'drag-strip'}
          style={{ height: 52, flex: 'none' }}
        />
        <div className="flex-1 flex flex-col justify-center" style={{ padding: '0 48px 52px' }}>
          {/* a quiet preview of the four layers the report will fill */}
          <div className="flex flex-col" style={{ gap: 12, opacity: 0.55 }}>
            {PREVIEW_LAYERS.map(([key, name]) => (
              <div key={key} className="flex items-center gap-3">
                <LayerTile layer={key} size={20} />
                <span className="secondary">{name}</span>
              </div>
            ))}
          </div>
          <div className="t13 secondary" style={{ marginTop: 24 }}>
            拖入论文后，四项检查的结果会出现在这里。
          </div>
        </div>
      </aside>
    </div>
  )
}
