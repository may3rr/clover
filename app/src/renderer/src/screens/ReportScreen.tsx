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
  reconcileFilter,
  refLine,
  type ListItem,
} from '../lib/items'
import {
  segmentsForParagraph,
  HL_CLASS,
  HL_SELECTED_CLASS,
} from '../lib/highlight'
import { apiFetch } from '../lib/api'
import { morph } from '../lib/vt'
import type { Prefs } from '../lib/prefs'
import Detail from './Detail'
import AccountChip from '../components/AccountChip'
import HistoryRow from '../components/HistoryRow'
import { useReports, type ReportMeta } from '../lib/useReports'
import { SideIcon, LAYER_SIDE } from '../components/SideIcons'
import {
  ArrowUpDocFillIcon,
  PageIcon,
  DocMagnifyIcon,
  SealOkIllustration,
  SevGlyph,
} from '../components/Icons'

const LAYER_NAMES: Record<string, string> = {
  authenticity: '文献真实性',
  support: '论断支持度',
  distribution: '引用分布',
  norms: '格式规范',
}
const LAYER_ORDER = ['authenticity', 'support', 'distribution', 'norms']

interface Props {
  report: Report
  jobId: string
  externalSelection?: { id: string | null; open: boolean } | null
  externalFilter?: { layer: string | null } | null
  registerExport: (fn: () => void) => void
  onExported: (path: string | null) => void
  onReset: () => void
  onOpenReport: (id: string) => void
  prefs: Prefs
  onOpenSettings: () => void
}

/** 303 → "5 分 3 秒", 20 → "20 秒" */
function duration(sec: number): string {
  const t = Math.round(sec)
  const m = Math.floor(t / 60)
  const r = t % 60
  if (!m) return `${r} 秒`
  return r ? `${m} 分 ${r} 秒` : `${m} 分钟`
}

export default function ReportScreen({
  report,
  jobId,
  externalSelection,
  externalFilter,
  registerExport,
  onExported,
  onReset,
  onOpenReport,
  prefs,
  onOpenSettings,
}: Props) {
  const { reports: history, remove: removeReport } = useReports()
  const items = useMemo(() => buildItems(report), [report])
  const [filter, setFilter] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [scrolled, setScrolled] = useState(false)
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
      const r = await apiFetch(`/reports/${jobId}/export`, { method: 'POST' })
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

  // E2E: open a support detail briefly, then export fires itself
  useEffect(() => {
    if (!window.citecheck.e2eFile) return
    const first = items.find(
      (i) => i.kind === 'finding' && i.layer === 'support'
    )
    if (first) select(first.id, true)
    const t = setTimeout(doExport, 1800)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ------------------------------------------------------ selection nav
  const select = useCallback(
    (id: string | null, openDetail: boolean) => {
      // list → detail morphs via a View Transition (skipped when reduced)
      if (openDetail) {
        morph(() => {
          setSelectedId(id)
          setDetailId(id)
        })
      } else {
        setSelectedId(id)
        setDetailId(null)
      }
      if (id) {
        // after the commit: scroll the highlighted paper segment into view
        // and keep the selected list row visible
        setTimeout(() => {
          const segs = segRefs.current.get(id) ?? []
          segs[0]?.scrollIntoView({ block: 'center' })
          // a brief pulse so the eye lands on the passage
          for (const el of segs) {
            el.classList.remove('hl-flash')
            void el.offsetWidth // restart the animation on repeat picks
            el.classList.add('hl-flash')
          }
          document
            .querySelector('.list-row.sel')
            ?.scrollIntoView({ block: 'nearest' })
        }, 0)
      }
    },
    []
  )

  const closeDetail = useCallback(() => {
    morph(() => setDetailId(null))
  }, [])

  // sidebar filter click: the inspector returns to the list for that filter
  // (a detail left open would keep showing the old item under the new
  // filter's back label)
  const changeFilter = useCallback(
    (next: string | null) => {
      const apply = () => {
        const r = reconcileFilter(items, next, selectedId)
        setFilter(next)
        setSelectedId(r.selectedId)
        setDetailId(r.detailId)
      }
      if (detailId !== null) morph(apply)
      else apply()
    },
    [items, selectedId, detailId]
  )

  useEffect(() => {
    if (externalSelection) {
      select(externalSelection.id, externalSelection.open)
    }
  }, [externalSelection, select])

  useEffect(() => {
    // screenshot-mode driver: sets the filter only, selection is driven
    // separately by externalSelection
    if (externalFilter) setFilter(externalFilter.layer)
  }, [externalFilter])

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
        if (selectedId) select(selectedId, true)
      } else if (e.key === 'Escape') {
        closeDetail()
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [shown, selectedId, detailId, select, closeDetail])

  const filterName = filter ? LAYER_NAMES[filter] : '全部问题'
  const fileName = report.document.filename ?? report.document.title ?? '论文'

  // sidebar history: the stored list, plus a synthetic row for the current
  // report when it isn't persisted (e.g. screenshot mode)
  const historyList = useMemo(() => {
    if (history.some((h) => h.id === jobId)) return history
    const cur: ReportMeta = {
      id: jobId,
      filename: fileName,
      title: (report.document.title ?? '').trim() || fileName,
      created_at: new Date().toISOString(),
      n_high: items.filter((i) => i.severity === 'high').length,
      n_medium: items.filter((i) => i.severity === 'medium').length,
      n_low: items.filter((i) => i.severity === 'low').length,
    }
    return [cur, ...history]
  }, [history, jobId, fileName, report, items])

  return (
    <div className="relative h-full overflow-hidden">
      {/* ---------- flush sidebar pane (vibrancy) ---------- */}
      <aside className="glass-sidebar flex flex-col">
        <div className="drag-strip" style={{ height: 52, flex: 'none' }} />
        <div className="group-label" style={{ fontWeight: 600 }}>
          检查结果
        </div>
        <nav className="flex flex-col" style={{ padding: '0 8px' }}>
          <SideRow
            icon={<SideIcon name="all" />}
            label="全部问题"
            count={items.length}
            active={filter === null}
            onClick={() => changeFilter(null)}
          />
          {LAYER_ORDER.map((key) => (
            <SideRow
              key={key}
              icon={
                <SideIcon
                  name={LAYER_SIDE[key].icon}
                  hue={LAYER_SIDE[key].hue}
                />
              }
              label={LAYER_NAMES[key]}
              count={counts[key] ?? 0}
              active={filter === key}
              onClick={() => changeFilter(key)}
            />
          ))}
        </nav>
        <div className="group-label" style={{ fontWeight: 600, marginTop: 16 }}>
          最近检查
        </div>
        <div
          className="flex-1 overflow-y-auto flex flex-col gap-1"
          style={{ padding: '0 8px 8px' }}
        >
          <button className="side-row" onClick={onReset}>
            <SideIcon name="plus" />
            <span className="font-normal">检查另一篇</span>
          </button>
          {historyList.map((h) => (
            <HistoryRow
              key={h.id}
              meta={h}
              active={h.id === jobId}
              onOpen={() => onOpenReport(h.id)}
              onDelete={() => removeReport(h.id)}
            />
          ))}
        </div>
        <div style={{ padding: '0 12px 12px' }}>
          <AccountChip prefs={prefs} onOpen={onOpenSettings} />
        </div>
      </aside>

      {/* ---------- content between sidebar and inspector ---------- */}
      <div
        className="flex flex-col h-full"
        style={{ marginLeft: 240, marginRight: 380, background: 'var(--bg)' }}
      >
        <div
          className={`drag-strip bar-solid strip-edge flex items-center justify-between${scrolled ? ' scrolled' : ''}`}
          style={{ height: 52, flex: 'none', padding: '0 24px' }}
        >
          <div className="font-semibold">{filterName}</div>
          <div className="flex items-center gap-3">
            {exported && (
              <span className="t13 secondary">已导出到 {exported}</span>
            )}
            {exportErr && <span className="t13 secondary">{exportErr}</span>}
            <button
              className="pill-accent"
              onClick={doExport}
              disabled={exporting}
            >
              {exporting ? (
                <svg
                  className="spinner"
                  width="13"
                  height="13"
                  viewBox="0 0 14 14"
                  aria-hidden
                >
                  <circle
                    cx="7"
                    cy="7"
                    r="5.5"
                    fill="none"
                    stroke="white"
                    strokeOpacity={0.4}
                    strokeWidth="2"
                  />
                  <path
                    d="M 7 1.5 A 5.5 5.5 0 0 1 12.5 7"
                    fill="none"
                    stroke="white"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                </svg>
              ) : (
                <ArrowUpDocFillIcon size={15} color="white" />
              )}
              {exporting ? '正在导出' : '导出到 Word'}
            </button>
          </div>
        </div>
        <main
          className={`paper flex-1 overflow-y-auto${selectedId ? ' has-sel' : ''}`}
          onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 0)}
          style={{
            padding: '0 24px 48px',
            background: 'var(--bg)',
            viewTransitionName: 'cc-paper',
          }}
        >
          <div style={{ maxWidth: 680, margin: '0 auto' }}>
            <PaperBody
              report={report}
              items={items}
              filter={filter}
              selectedId={selectedId}
              segRefs={segRefs}
              onPick={(ids) => {
                const covering = items.filter((i) => ids.includes(i.id))
                const it = pickItem(covering)
                if (it) select(it.id, true)
              }}
            />
          </div>
        </main>
      </div>

      {/* ---------- inspector ---------- */}
      <aside
        className="inspector"
        style={{ viewTransitionName: 'cc-panel' }}
      >
        {detail ? (
          <Detail
            item={detail}
            report={report}
            backLabel={filterName}
            onBack={closeDetail}
          />
        ) : (
          <InspectorList
            items={shown}
            report={report}
            grouped={filter === null}
            selectedId={selectedId}
            onSelect={(id) => select(id, true)}
          />
        )}
      </aside>
    </div>
  )
}

function SideRow({
  icon,
  label,
  count,
  active,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  count?: number
  active?: boolean
  onClick?: () => void
}) {
  return (
    <button
      className={`side-row ${active ? 'sel' : ''}`}
      style={{ fontWeight: active ? 600 : 400 }}
      onClick={onClick}
    >
      {icon}
      <span className="flex-1 text-left">{label}</span>
      {count !== undefined && <span className="t13 secondary">{count}</span>}
    </button>
  )
}

function PaperBody({
  report,
  items,
  filter,
  selectedId,
  segRefs,
  onPick,
}: {
  report: Report
  items: ListItem[]
  filter: string | null
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
  const refParaIds = useMemo(
    () =>
      new Set(
        (report.references ?? [])
          .map((r) => r.paragraph_id)
          .filter(Boolean) as string[]
      ),
    [report.references]
  )
  // visible highlights: only the active filter; low + renumber-group items
  // only paint once selected
  const visible = useMemo(
    () =>
      items.filter((i) => {
        if (filter && i.layer !== filter) return false
        if (i.id === selectedId) return true
        if (i.kind === 'group' || i.severity === 'low') return false
        return true
      }),
    [items, filter, selectedId]
  )
  const title = (report.document.title ?? '').trim()
  const nMarkers = (report.markers ?? []).length
  const nRefs = (report.references ?? []).length
  const nHigh = items.filter((i) => i.severity === 'high').length
  const nMedium = items.filter(
    (i) => i.severity === 'medium' || i.severity === 'low'
  ).length

  return (
    <>
      {/* Notion-style page header */}
      <div className="rise-in">
        <PageIcon />
        <div
          className="t32"
          style={{ fontWeight: 700, marginTop: 12, lineHeight: 1.25 }}
        >
          {title}
        </div>
        <div style={{ marginTop: 24 }}>
          {(
            [
              ['文件', report.document.filename ?? '—'],
              ['引用标记', `${nMarkers} 处`],
              ['参考文献', `${nRefs} 条`],
              [
                '对标领域',
                report.distribution?.benchmark_name ?? '—',
              ],
              [
                '检查用时',
                duration(report.meta?.duration_s ?? 0),
              ],
            ] as [string, string][]
          ).map(([label, value]) => (
            <div key={label} className="prop-row">
              <span className="prop-label">{label}</span>
              <span className="prop-value font-normal">{value}</span>
            </div>
          ))}
        </div>
        <div className="callout" style={{ marginTop: 24, marginBottom: 40 }}>
          <DocMagnifyIcon size={20} color="var(--accent)" />
          <div className="font-normal">
            {nHigh + nMedium === 0 ? (
              '没有发现严重问题，其余提示导出后会以批注和修订出现在 Word 里。'
            ) : (
              <>
                发现
                {nHigh > 0 && (
                  <>
                    {' '}
                    <span className="font-semibold sem-high">{nHigh}</span>{' '}
                    条严重问题{nMedium > 0 ? '，' : ''}
                  </>
                )}
                {nMedium > 0 && (
                  <>
                    {' '}
                    <span className="font-semibold sem-medium">{nMedium}</span>{' '}
                    条需要注意
                  </>
                )}
                ，导出后会以批注和修订出现在 Word 里。
              </>
            )}
          </div>
        </div>
      </div>
      {(report.paragraphs ?? []).map((p) => {
        const ptext = p.text ?? ''
        if (title && ptext.trim() === title) return null // shown once above
        const isHeading = headingIds.has(p.id ?? '')
        const isRef = refParaIds.has(p.id ?? '')
        const segs = segmentsForParagraph(ptext, p.id ?? '', visible, selectedId)
        return (
          <p
            key={p.id}
            className={isRef ? 'paper-refs' : undefined}
            style={{
              fontWeight: isHeading ? 600 : 400,
              fontSize: isHeading ? 20 : undefined,
              margin: 0,
              marginTop: isHeading ? 32 : 0,
              marginBottom: 16,
            }}
          >
            {segs.map((s, i) => {
              if (s.severity === null) return <span key={i}>{s.text}</span>
              const cls = s.selected
                ? HL_SELECTED_CLASS[s.severity]
                : HL_CLASS[s.severity]
              // adjacent marks read as one run: no inner padding/radius
              const jl = segs[i - 1]?.severity != null ? ' hl-jl' : ''
              const jr = segs[i + 1]?.severity != null ? ' hl-jr' : ''
              return (
                <span
                  key={i}
                  className={`hl ${cls}${jl}${jr}`}
                  ref={(el) => {
                    if (!el) return
                    for (const id of s.itemIds) {
                      const arr = segRefs.current.get(id) ?? []
                      if (!arr.includes(el))
                        segRefs.current.set(id, [...arr, el])
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

function InspectorList({
  items,
  report,
  grouped,
  selectedId,
  onSelect,
}: {
  items: ListItem[]
  report: Report
  grouped: boolean
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const groups = useMemo(() => {
    if (!grouped) return null
    const out: { layer: string; items: ListItem[] }[] = []
    for (const key of LAYER_ORDER) {
      const l = items.filter((i) => i.layer === key)
      if (l.length) out.push({ layer: key, items: l })
    }
    return out
  }, [items, grouped])

  let rowIdx = 0
  const row = (i: ListItem) => {
    // staggered entrance — max 12 rows animate, the rest are instant
    const delay = Math.min(rowIdx++, 12) * 20
    const sub = refLine(i, report) ?? firstLine(i.detail)
    return (
      <button
        key={i.id}
        className={`list-row row-in ${i.id === selectedId ? 'sel' : ''}`}
        style={{ animationDelay: `${delay}ms` }}
        onClick={() => onSelect(i.id)}
      >
        <div className="flex items-start gap-2">
          <span style={{ marginTop: 1, flex: 'none' }}>
            <SevGlyph severity={i.severity} />
          </span>
          <div className="min-w-0">
            <div
              className={`font-semibold${i.id === selectedId ? ' row-title-sel' : ''}`}
            >
              {i.title}
            </div>
            {sub && <div className="t13 secondary truncate">{sub}</div>}
          </div>
        </div>
      </button>
    )
  }

  return (
    <>
      <div
        className="font-semibold bar-solid-subtle drag-strip"
        style={{ fontSize: 17, padding: '14px 16px', flex: 'none', height: 52 }}
      >
        {items.length} 个问题
      </div>
      <div
        className="flex-1 overflow-y-auto flex flex-col gap-1"
        style={{ padding: '0 8px 8px' }}
      >
        {items.length === 0 && (
          <div
            className="flex flex-col items-center secondary"
            style={{ padding: '32px 12px', gap: 12 }}
          >
            <SealOkIllustration size={40} />
            <div className="t13">这一类没有发现问题。</div>
          </div>
        )}
        {groups
          ? groups.map((g) => (
              <div key={g.layer}>
                <div className="group-label">
                  {LAYER_NAMES[g.layer]} {g.items.length}
                </div>
                {g.items.map(row)}
              </div>
            ))
          : items.map(row)}
      </div>
    </>
  )
}
