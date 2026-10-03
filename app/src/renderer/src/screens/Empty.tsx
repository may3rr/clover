import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../lib/api'
import {
  PapersIllustration,
  ChevronDownIcon,
  DocTextFillIcon,
  TrashFillIcon,
  SealOkIllustration,
  LayerTile,
} from '../components/Icons'
import AccountChip from '../components/AccountChip'
import { relDay } from '../lib/reltime'
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

interface ReportMeta {
  id: string
  filename: string
  title: string
  created_at: string
  n_high: number
  n_medium: number
  n_low: number
}

const SHOT_HISTORY: ReportMeta[] = [
  {
    id: 'shot-1',
    filename: 'numeric_en.docx',
    title: 'Citation Behaviour in Neural Models',
    created_at: new Date(Date.now() - 86400000).toISOString(),
    n_high: 3,
    n_medium: 11,
    n_low: 1,
  },
  {
    id: 'shot-2',
    filename: 'hallucination_survey.docx',
    title: 'A Survey of Hallucination',
    created_at: new Date(Date.now() - 3 * 86400000).toISOString(),
    n_high: 1,
    n_medium: 6,
    n_low: 2,
  },
  {
    id: 'shot-3',
    filename: 'retrieval_paper.docx',
    title: 'Dense Passage Retrieval',
    created_at: new Date(Date.now() - 9 * 86400000).toISOString(),
    n_high: 0,
    n_medium: 4,
    n_low: 3,
  },
]

/** Home: the three-pane shell with history in the sidebar and the drop
 *  zone as the reading area — the window never shows a bare whiteboard. */
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
  const [history, setHistory] = useState<ReportMeta[]>([])

  useEffect(() => {
    apiFetch('/benchmarks')
      .then((r) => r.json())
      .then((b: Bench[]) => setBenches(b))
      .catch(() => setBenches([]))
    if (window.citecheck.shotsMode) {
      setHistory(SHOT_HISTORY)
      return
    }
    apiFetch('/reports')
      .then((r) => r.json())
      .then((h: ReportMeta[]) => setHistory(Array.isArray(h) ? h : []))
      .catch(() => setHistory([]))
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

  const removeReport = useCallback((id: string) => {
    setHistory((h) => h.filter((r) => r.id !== id))
    if (window.citecheck.shotsMode) return
    apiFetch(`/reports/${id}`, { method: 'DELETE' }).catch(() => {})
  }, [])

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
          {history.length === 0 && (
            <div className="t13 secondary" style={{ padding: '4px 12px' }}>
              检查过的论文会出现在这里
            </div>
          )}
          {history.map((h) => (
            <HistoryRow
              key={h.id}
              meta={h}
              onOpen={() => onOpenReport(h.id)}
              onDelete={() => removeReport(h.id)}
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
        <div className="flex-1 flex flex-col items-center justify-center gap-2">
          <SealOkIllustration size={40} />
          <div className="t13 secondary">检查结果会出现在这里</div>
        </div>
      </aside>
    </div>
  )
}

function HistoryRow({
  meta,
  onOpen,
  onDelete,
}: {
  meta: ReportMeta
  onOpen: () => void
  onDelete: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const arm = (e: React.MouseEvent) => {
    e.stopPropagation()
    setConfirming(true)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setConfirming(false), 3000)
  }
  const confirm = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (timer.current) clearTimeout(timer.current)
    onDelete()
  }

  return (
    <button className="hist-row" onClick={onOpen}>
      <span className="hist-row-main min-w-0">
        <LayerTile
          size={20}
          icon={<DocTextFillIcon size={12} />}
        />
        <span className="min-w-0">
          <span className="hist-row-name">{meta.filename}</span>
          <span className="t13 secondary hist-row-sub">
            {relDay(meta.created_at)}
            {meta.n_high > 0 && ` · ${meta.n_high} 严重`}
          </span>
        </span>
      </span>
      {confirming ? (
        <span
          className="t13 hist-row-del confirming"
          role="button"
          tabIndex={0}
          onClick={confirm}
          onKeyDown={(e) => e.key === 'Enter' && confirm(e as never)}
        >
          删除
        </span>
      ) : (
        <span
          className="hist-row-del"
          role="button"
          tabIndex={0}
          aria-label={`删除 ${meta.filename} 的检查记录`}
          onClick={arm}
          onKeyDown={(e) => e.key === 'Enter' && arm(e as never)}
        >
          <TrashFillIcon size={13} color="var(--text-secondary)" />
        </span>
      )}
    </button>
  )
}
