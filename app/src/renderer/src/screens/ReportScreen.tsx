import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { Report } from '../types/report'
import {
  buildItems,
  firstLine,
  moveSelection,
  pickItem,
  type ListItem,
} from '../lib/items'
import { segmentsForParagraph, HL_CLASS } from '../lib/highlight'
import { apiFetch } from '../lib/api'
import Detail from './Detail'

const LAYER_NAMES: Record<string, string> = {
  authenticity: '文献真实性',
  support: '论断支持度',
  distribution: '引用分布',
  norms: '格式规范',
}

interface Props {
  report: Report
  jobId: string
  /** shot/E2E driver: selection applied after mount via effect */
  externalSelection?: { id: string | null; open: boolean } | null
  registerExport: (fn: () => void) => void
  onExported: (path: string | null) => void
}

export default function ReportScreen({
  report,
  jobId,
  externalSelection,
  registerExport,
  onExported,
}: Props) {
  const items = useMemo(() => buildItems(report), [report])
  const [filter, setFilter] = useState<string | null>(null) // layer or null=all
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exported, setExported] = useState<string | null>(null)
  const [exportErr, setExportErr] = useState<string | null>(null)
  const segRefs = useRef(new Map<string, HTMLElement[]>())

  const shown = useMemo(
    () => (filter ? items.filter((i) => i.layer === filter) : items),
    [items, filter]
  )
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const i of items) c[i.layer] = (c[i.layer] ?? 0) + 1
    return c
  }, [items])

  const selected = items.find((i) => i.id === selectedId) ?? null
  const detail = items.find((i) => i.id === detailId) ?? null

  // ------------------------------------------------------------- export
  const doExport = useCallback(async () => {
    if (exporting) return
    setExporting(true)
    setExportErr(null)
    setExported(null)
    try {
      const r = await apiFetch(`/jobs/${jobId}/export`, { method: 'POST' })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setExportErr(d.detail ?? '导出失败。请重试。')
        setExporting(false)
        return
      }
      const { path } = (await r.json()) as { path: string }
      setExported(path.split('/').pop() ?? path)
      window.citecheck.revealInFinder(path)
      onExported(path)
      setTimeout(() => setExported(null), 4000)
    } catch {
      setExportErr('导出失败。请确认本地服务仍在运行。')
    }
    setExporting(false)
  }, [exporting, jobId, onExported])

  useEffect(() => {
    registerExport(doExport)
  }, [doExport, registerExport])

  // E2E: export fires itself once the report is on screen
  useEffect(() => {
    if (window.citecheck.e2eFile) doExport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ------------------------------------------------------ selection nav
  const select = useCallback(
    (id: string | null, openDetail: boolean) => {
      setSelectedId(id)
      setDetailId(openDetail ? id : null)
      if (id) {
        // scroll its paper segments into view
        requestAnimationFrame(() => {
          const el = segRefs.current.get(id)?.[0]
          el?.scrollIntoView({ block: 'center' })
        })
      }
    },
    []
  )
  useEffect(() => {
    if (externalSelection) select(externalSelection.id, externalSelection.open)
  }, [externalSelection, select])

  // --------------------------------------------------------------- keys
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'SELECT' || tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const next = moveSelection(
          shown,
          detailId ?? selectedId,
          e.key === 'ArrowDown' ? 1 : -1
        )
        if (next) select(next, detailId !== null)
      } else if (e.key === 'Enter') {
        if (selectedId) setDetailId(selectedId)
      } else if (e.key === 'Escape') {
        setDetailId(null)
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [shown, selectedId, detailId, select])

  const cloudCalls = report.meta?.llm_calls?.cloud ?? 0

  return (
    <div className="flex h-full">
      {/* ---------- left: vibrancy sidebar ---------- */}
      <aside
        className="flex flex-col"
        style={{ width: 240, paddingTop: 52, paddingLeft: 16, paddingRight: 8 }}
      >
        <div
          className="font-semibold clamp-2"
          style={{ fontSize: 15, lineHeight: 1.35, marginBottom: 24 }}
          title={report.document.title ?? ''}
        >
          {report.document.title ?? '未命名论文'}
        </div>
        <nav className="flex flex-col gap-1">
          <SidebarRow
            label="全部问题"
            count={items.length}
            active={filter === null}
            onClick={() => setFilter(null)}
          />
          {Object.entries(LAYER_NAMES).map(([key, name]) => (
            <SidebarRow
              key={key}
              label={name}
              count={counts[key] ?? 0}
              active={filter === key}
              onClick={() => setFilter(key)}
            />
          ))}
        </nav>
        <div className="flex-1" />
        <div className="font-normal" style={{ paddingBottom: 16 }}>
          <div>全文在本机解析</div>
          <div>云端复核 {cloudCalls} 次</div>
        </div>
      </aside>

      {/* ---------- center + right ---------- */}
      <div className="flex-1 flex flex-col min-w-0" style={{ background: 'var(--bg)' }}>
        <div
          className="drag-strip flex items-center justify-end gap-3"
          style={{ height: 52, paddingRight: 16, flex: 'none' }}
        >
          {exported && (
            <span className="font-normal">已导出到 {exported}</span>
          )}
          {exportErr && <span className="font-normal">{exportErr}</span>}
          <button className="pill-accent" onClick={doExport} disabled={exporting}>
            {exporting ? '正在导出' : '导出到 Word'}
          </button>
        </div>
        <div className="flex flex-1 min-h-0">
          {/* ---------- center: paper ---------- */}
          <main className="paper flex-1 overflow-y-auto" style={{ padding: '0 24px 48px' }}>
            <div style={{ maxWidth: 680, margin: '0 auto' }}>
              <PaperTitle report={report} />
              <PaperBody
                report={report}
                items={items}
                selectedId={selectedId}
                segRefs={segRefs}
                onPick={(ids) => {
                  const covering = items.filter((i) => ids.includes(i.id))
                  const it = pickItem(covering, (x) =>
                    x.kind === 'finding'
                      ? x.finding?.anchor?.end ?? x.start
                      : x.revision?.anchor?.end ?? x.start
                  )
                  if (it) select(it.id, true)
                }}
              />
            </div>
          </main>
          {/* ---------- right: list / detail ---------- */}
          <aside
            className="overflow-y-auto"
            style={{ width: 380, flex: 'none', padding: '0 16px 16px' }}
          >
            {detail ? (
              <Detail
                item={detail}
                report={report}
                onBack={() => setDetailId(null)}
              />
            ) : (
              <ItemList
                items={shown}
                selectedId={selectedId}
                onSelect={(id) => select(id, true)}
              />
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}

function SidebarRow({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      className={`sidebar-row flex justify-between items-center text-left ${active ? 'row-selected' : ''}`}
      style={{ fontWeight: active ? 600 : 400, width: '100%' }}
      onClick={onClick}
    >
      <span>{label}</span>
      <span>{count}</span>
    </button>
  )
}

function PaperTitle({ report }: { report: Report }) {
  if (!report.document.title) return null
  return (
    <div style={{ fontWeight: 700, marginBottom: 24 }}>
      {report.document.title}
    </div>
  )
}

function PaperBody({
  report,
  items,
  selectedId,
  segRefs,
  onPick,
}: {
  report: Report
  items: ListItem[]
  selectedId: string | null
  segRefs: React.MutableRefObject<Map<string, HTMLElement[]>>
  onPick: (itemIds: string[]) => void
}) {
  const headingIds = useMemo(
    () =>
      new Set(
        (report.sections ?? [])
          .map((s) => s.heading_paragraph_id)
          .filter(Boolean) as string[]
      ),
    [report.sections]
  )
  const byPara = useMemo(() => {
    const m = new Map<string, ListItem[]>()
    for (const i of items) {
      if (!i.paragraphId) continue
      m.set(i.paragraphId, [...(m.get(i.paragraphId) ?? []), i])
    }
    return m
  }, [items])

  return (
    <>
      {(report.paragraphs ?? []).map((p) => {
        const isHeading = headingIds.has(p.id ?? '')
        const segs = segmentsForParagraph(p.text ?? '', byPara.get(p.id ?? '') ?? [])
        return (
          <p
            key={p.id}
            style={{
              fontWeight: isHeading ? 600 : 400,
              margin: 0,
              marginBottom: 16,
            }}
          >
            {segs.map((s, i) => {
              if (s.severity === null) return <span key={i}>{s.text}</span>
              const isSel = s.itemIds.includes(selectedId ?? '')
              return (
                <span
                  key={i}
                  className={isSel ? 'hl-selected' : HL_CLASS[s.severity]}
                  ref={(el) => {
                    if (!el) return
                    for (const id of s.itemIds) {
                      const arr = segRefs.current.get(id) ?? []
                      if (!arr.includes(el)) segRefs.current.set(id, [...arr, el])
                    }
                  }}
                  onClick={() => onPick(s.itemIds)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && onPick(s.itemIds)}
                >
                  {s.text}
                </span>
              )
            })}
          </p>
        )
      })}
    </>
  )
}

function ItemList({
  items,
  selectedId,
  onSelect,
}: {
  items: ListItem[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <>
      <div className="font-semibold" style={{ padding: '8px 8px 16px' }}>
        {items.length} 个问题
      </div>
      <div className="flex flex-col gap-1">
        {items.map((i) => (
          <button
            key={i.id}
            className="text-left"
            style={{
              borderRadius: 12,
              padding: '8px 12px',
              background:
                i.id === selectedId ? 'var(--bg-subtle)' : 'transparent',
              width: '100%',
            }}
            onClick={() => onSelect(i.id)}
          >
            <div className="flex items-start gap-2">
              <span
                className={`dot ${i.severity === 'rev' ? 'dot-rev' : `dot-${i.severity}`}`}
                style={{ marginTop: 7 }}
              />
              <div className="min-w-0">
                <div className="font-semibold">{i.title}</div>
                {firstLine(i.detail) && (
                  <div className="font-normal clamp-2">{firstLine(i.detail)}</div>
                )}
              </div>
            </div>
          </button>
        ))}
      </div>
    </>
  )
}
