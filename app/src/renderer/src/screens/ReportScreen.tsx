import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { Paragraph, Report } from '../types/report'
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
import { mathPieces, type Piece } from '../lib/math'
import { apiFetch, getInfo } from '../lib/api'
import { assetUrl, layoutBlocks } from '../lib/layout'
import { morph } from '../lib/vt'
import { useScrollFade } from '../lib/useScrollFade'
import type { Prefs } from '../lib/prefs'
import Detail from './Detail'
import AccountChip from '../components/AccountChip'
import HistoryRow from '../components/HistoryRow'
import ExportDone from '../components/ExportDone'
import PaperSearch from '../components/PaperSearch'
import { MagnifierIcon } from '../components/Icons'
import OverviewCard from '../components/OverviewCard'
import { useReports, type ReportMeta } from '../lib/useReports'
import { SideIcon, LAYER_SIDE } from '../components/SideIcons'
import {
  ArrowUpDocFillIcon,
  PageIcon,
  DocMagnifyIcon,
  SealOkIllustration,
  SevGlyph,
  SidebarLeadingIcon,
  SidebarTrailingIcon,
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
  /** 期刊对标后到：覆盖 report.overview，report 对象本身保持不变，
   *  这样条目、选中和高亮都不会因为对标到达而重建 */
  overview?: Report['overview']
  jobId: string
  externalSelection?: { id: string | null; open: boolean } | null
  externalFilter?: { layer: string | null } | null
  /** screenshot driver: force pane collapse for shot states */
  shotPanes?: { left: boolean; right: boolean } | null
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
  overview: lateOverview,
  jobId,
  externalSelection,
  externalFilter,
  shotPanes,
  registerExport,
  onExported,
  onReset,
  onOpenReport,
  prefs,
  onOpenSettings,
}: Props) {
  const { reports: history, remove: removeReport } = useReports()
  const items = useMemo(() => buildItems(report), [report])
  const overview = lateOverview !== undefined ? lateOverview : report.overview
  const [filter, setFilter] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [exported, setExported] = useState<string | null>(null)
  const [exportErr, setExportErr] = useState<string | null>(null)
  const isTex = report.document.source_format === 'tex'
  const segRefs = useRef(new Map<string, HTMLElement[]>())
  const paperRef = useRef<HTMLElement>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchTick, setSearchTick] = useState(0)
  const [sideTab, setSideTab] = useState<'toc' | 'history'>(() => {
    try {
      return localStorage.getItem('cc-side-tab') === 'history'
        ? 'history'
        : 'toc'
    } catch {
      return 'toc'
    }
  })
  const pickSideTab = (t: 'toc' | 'history') => {
    setSideTab(t)
    try {
      localStorage.setItem('cc-side-tab', t)
    } catch {
      // per-viewer convenience only
    }
  }

  // pane collapse — per-viewer layout memory, same pattern as cc-side-tab.
  // paneAnim stays off through the first frame so a restored collapse lands
  // in place instead of playing the slide on every report open
  const [leftCollapsed, setLeftCollapsed] = useState(() => {
    try {
      return localStorage.getItem('cc-pane-left') === '1'
    } catch {
      return false
    }
  })
  const [rightCollapsed, setRightCollapsed] = useState(() => {
    try {
      return localStorage.getItem('cc-pane-right') === '1'
    } catch {
      return false
    }
  })
  const [paneAnim, setPaneAnim] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setPaneAnim(true))
    return () => cancelAnimationFrame(r)
  }, [])
  // screenshot driver may force pane states (per-shot, not persisted)
  useEffect(() => {
    if (!shotPanes) return
    setLeftCollapsed(shotPanes.left)
    setRightCollapsed(shotPanes.right)
  }, [shotPanes])
  const toggleLeftPane = useCallback(() => {
    setLeftCollapsed((v) => {
      const next = !v
      try {
        localStorage.setItem('cc-pane-left', next ? '1' : '0')
      } catch {
        // per-viewer convenience only
      }
      return next
    })
  }, [])
  const toggleRightPane = useCallback(() => {
    setRightCollapsed((v) => {
      const next = !v
      try {
        localStorage.setItem('cc-pane-right', next ? '1' : '0')
      } catch {
        // per-viewer convenience only
      }
      return next
    })
  }, [])
  const [activeSection, setActiveSection] = useState<string | null>(null)

  // toc/history list edge fade
  const {
    ref: sideScrollRef,
    fadeClass: sideFade,
  } = useScrollFade<HTMLDivElement>()

  const shown = useMemo(
    () => (filter ? items.filter((i) => i.layer === filter) : items),
    [items, filter]
  )
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const i of items) c[i.layer] = (c[i.layer] ?? 0) + 1
    return c
  }, [items])

  // sidebar outline: titled sections, with their high/medium issue count
  const docTitle = (report.document.title ?? '').trim()
  const outline = useMemo(() => {
    const secOf = new Map<string, string>()
    for (const p of report.paragraphs ?? [])
      if (p.id) secOf.set(p.id, p.section_id ?? '')
    const n: Record<string, number> = {}
    for (const i of items) {
      if (i.severity === 'low' || !i.paragraphId) continue
      const sid = secOf.get(i.paragraphId)
      if (sid) n[sid] = (n[sid] ?? 0) + 1
    }
    return (report.sections ?? [])
      .filter((x) => {
        const t = (x.title ?? '').trim()
        // the paper title is shown once in the page header, not as a heading
        return t && x.heading_paragraph_id && t !== docTitle
      })
      .map((x) => ({
        id: x.id,
        title: (x.title ?? '').trim(),
        pid: x.heading_paragraph_id as string,
        issues: n[x.id] ?? 0,
      }))
  }, [report, items, docTitle])

  const jumpTo = useCallback((pid: string) => {
    const root = paperRef.current
    const el = root?.querySelector<HTMLElement>(`[data-pid="${pid}"]`)
    if (!root || !el) return
    const top =
      el.getBoundingClientRect().top - root.getBoundingClientRect().top
    root.scrollTo({
      top: root.scrollTop + top - 16,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'auto'
        : 'smooth',
    })
  }, [])

  // scroll spy: the last section heading above the top third of the pane
  const spyFrame = useRef(0)
  const onPaperScroll = (root: HTMLElement) => {
    setScrolled(root.scrollTop > 0)
    if (spyFrame.current) return
    spyFrame.current = requestAnimationFrame(() => {
      spyFrame.current = 0
      const line = root.getBoundingClientRect().top + root.clientHeight / 3
      let cur: string | null = null
      for (const o of outline) {
        const el = root.querySelector(`[data-pid="${o.pid}"]`)
        if (el && el.getBoundingClientRect().top <= line) cur = o.id
        else if (el) break
      }
      setActiveSection(cur)
    })
  }

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
      setExported(path)
      onExported(path)
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
    (id: string | null, openDetail: boolean, viaKey = false) => {
      // list → detail morphs via a View Transition (skipped when reduced);
      // arrowing through items with the detail open switches instantly
      if (openDetail && !viaKey) {
        morph(() => {
          setSelectedId(id)
          setDetailId(id)
        })
      } else {
        setSelectedId(id)
        setDetailId(openDetail ? id : null)
      }
      if (id) {
        // after the commit: scroll the highlighted paper segment into view
        // and keep the selected list row visible
        setTimeout(() => {
          const segs = segRefs.current.get(id) ?? []
          // within a screen: glide; further away: jump
          const r = segs[0]?.getBoundingClientRect()
          const near =
            r != null &&
            Math.abs(r.top + r.height / 2 - window.innerHeight / 2) <
              window.innerHeight
          segs[0]?.scrollIntoView({
            block: 'center',
            behavior: near ? 'smooth' : 'auto',
          })
          // the passage settles into its highlight once
          for (const el of segs) {
            el.classList.remove('hl-land')
            void el.offsetWidth // restart the animation on repeat picks
            el.classList.add('hl-land')
          }
          document
            .querySelector('.list-row.sel')
            ?.scrollIntoView({ block: 'nearest' })
        }, 0)
      }
    },
    []
  )

  const closeExported = useCallback(() => setExported(null), [])

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
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        setSearchOpen(true)
        setSearchTick((t) => t + 1)
        return
      }
      if ((e.metaKey || e.ctrlKey) && e.key === '\\') {
        e.preventDefault()
        if (e.shiftKey) toggleRightPane()
        else toggleLeftPane()
        return
      }
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'SELECT' || tag === 'INPUT' || tag === 'TEXTAREA') return
      // the inspector is hidden — its list/detail keys would change state
      // the user cannot see
      if (rightCollapsed && ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(e.key))
        return
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const next = moveSelection(
          shown,
          detailId ?? selectedId,
          e.key === 'ArrowDown' ? 1 : -1
        )
        if (next) select(next, detailId !== null, true)
      } else if (e.key === 'Enter') {
        if (selectedId) select(selectedId, true)
      } else if (e.key === 'Escape') {
        closeDetail()
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [
    shown,
    selectedId,
    detailId,
    select,
    closeDetail,
    rightCollapsed,
    toggleLeftPane,
    toggleRightPane,
  ])

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
    <div
      className={`relative h-full overflow-hidden${paneAnim ? ' pane-anim' : ''}`}
    >
      {/* ---------- flush sidebar pane (vibrancy) ---------- */}
      <aside className={`glass-sidebar${leftCollapsed ? ' collapsed' : ''}`}>
        <div className="side-inner">
          <div
            className="drag-strip flex items-center"
            style={{ height: 52, flex: 'none', paddingLeft: 84 }}
          >
            <button
              className="icon-btn"
              aria-label="收起侧栏"
              title="收起侧栏 ⌘\"
              onClick={toggleLeftPane}
            >
              <SidebarLeadingIcon size={15} />
            </button>
          </div>
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
          <div className="side-tabs" role="tablist">
            {(
              [
                ['toc', '目录'],
                ['history', '最近检查'],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={sideTab === key}
                className={`side-tab${sideTab === key ? ' on' : ''}`}
                onClick={() => pickSideTab(key)}
              >
                {label}
              </button>
            ))}
          </div>
          <div
            ref={sideScrollRef}
            className={`side-scroll fade-scroll flex-1 overflow-y-auto flex flex-col gap-1${sideFade ? ` ${sideFade}` : ''}`}
          >
            {sideTab === 'toc' ? (
              outline.length ? (
                outline.map((o) => (
                  <button
                    key={o.id}
                    className={`side-row toc-row${activeSection === o.id ? ' sel' : ''}`}
                    onClick={() => jumpTo(o.pid)}
                    title={o.title}
                  >
                    <span className="flex-1 truncate">{o.title}</span>
                    {o.issues > 0 && (
                      <span className="t13 secondary">{o.issues}</span>
                    )}
                  </button>
                ))
              ) : (
                <div className="t13 secondary" style={{ padding: '4px 12px' }}>
                  这篇论文没有识别出章节标题。
                </div>
              )
            ) : (
              <>
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
              </>
            )}
          </div>
          <div style={{ padding: '0 12px 12px' }}>
            <AccountChip prefs={prefs} onOpen={onOpenSettings} />
          </div>
        </div>
      </aside>

      {/* ---------- content between sidebar and inspector ---------- */}
      <div
        className={`center-pane flex flex-col h-full${leftCollapsed ? ' no-left' : ''}${rightCollapsed ? ' no-right' : ''}`}
      >
        <div
          className={`drag-strip bar-solid strip-edge flex items-center justify-between${scrolled ? ' scrolled' : ''}`}
          style={{ height: 52, flex: 'none' }}
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {leftCollapsed && (
              <button
                className="icon-btn"
                aria-label="展开侧栏"
                title="展开侧栏 ⌘\"
                onClick={toggleLeftPane}
              >
                <SidebarLeadingIcon size={15} />
              </button>
            )}
            {searchOpen ? (
              <PaperSearch
                rootRef={paperRef}
                focusTick={searchTick}
                onClose={() => setSearchOpen(false)}
              />
            ) : (
              <div className="font-semibold">{filterName}</div>
            )}
          </div>
          <div className="relative flex items-center gap-3">
            {!searchOpen && (
              <button
                className="icon-btn"
                aria-label="在正文中查找"
                title="在正文中查找 ⌘F"
                onClick={() => {
                  setSearchOpen(true)
                  setSearchTick((t) => t + 1)
                }}
              >
                <MagnifierIcon size={15} />
              </button>
            )}
            {rightCollapsed && (
              <button
                className="icon-btn"
                aria-label="展开检查器"
                title="展开检查器 ⌘⇧\"
                onClick={toggleRightPane}
              >
                <SidebarTrailingIcon size={15} />
              </button>
            )}
            {exported && (
              <ExportDone
                path={exported}
                tex={isTex}
                onClose={closeExported}
              />
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
              {exporting
                ? '正在导出'
                : isTex
                  ? '导出批注版源码'
                  : '导出到 Word'}
            </button>
          </div>
        </div>
        <main
          className={`paper flex-1 overflow-y-auto${selectedId ? ' has-sel' : ''}${scrolled ? ' is-scrolled' : ''}`}
          ref={paperRef}
          onScroll={(e) => onPaperScroll(e.currentTarget)}
          style={{
            padding: '0 24px 48px',
            background: 'var(--bg)',
            viewTransitionName: 'cc-paper',
          }}
        >
          <div style={{ maxWidth: 680, margin: '0 auto' }}>
            <PaperBody
              report={report}
              overview={overview}
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
        className={`inspector${rightCollapsed ? ' collapsed' : ''}`}
        style={{ viewTransitionName: 'cc-panel' }}
      >
        <div className="insp-inner">
          {detail ? (
            <Detail
              item={detail}
              report={report}
              backLabel={filterName}
              onBack={closeDetail}
              onCollapse={toggleRightPane}
              onJump={jumpTo}
            />
          ) : (
            <InspectorList
              items={shown}
              report={report}
              grouped={filter === null}
              selectedId={selectedId}
              onSelect={(id) => select(id, true)}
              onCollapse={toggleRightPane}
            />
          )}
        </div>
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

/** "《数据分析与知识发现》范文 32 篇" / built-in baseline / benchmark name */
export function benchLabel(report: Report): string {
  const d = report.distribution
  if (!d) return '—'
  if (d.venue && d.venue_source === 'exemplars')
    return `《${d.venue}》，文献文件夹中的 ${d.n_papers} 篇论文`
  if (d.venue && d.venue_source === 'builtin')
    return `《${d.venue}》，内置基线 ${d.n_papers} 篇论文`
  return d.benchmark_name ?? '—'
}

function PaperBody({
  report,
  overview,
  items,
  filter,
  selectedId,
  segRefs,
  onPick,
}: {
  report: Report
  overview: Report['overview']
  items: ListItem[]
  filter: string | null
  selectedId: string | null
  segRefs: React.MutableRefObject<Map<string, HTMLElement[]>>
  onPick: (itemIds: string[]) => void
}) {
  const exportWhere =
    report.document.source_format === 'tex'
      ? '导出后会以注释写进 LaTeX 源码，修订另附补丁文件'
      : '导出后会以批注和修订出现在 Word 里'
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
  const blocks = useMemo(
    () => layoutBlocks(report.paragraphs ?? []),
    [report.paragraphs]
  )
  const [server, setServer] = useState<{
    baseUrl: string
    token: string
  } | null>(null)
  const bundle = report.document.assets
  useEffect(() => {
    if (!bundle) return
    let live = true
    getInfo().then((i) => live && setServer(i))
    return () => {
      live = false
    }
  }, [bundle])
  const figureUrl = (name: string): string | null =>
    bundle && server
      ? assetUrl(server.baseUrl, server.token, bundle, name)
      : null

  // paragraph text with highlight marks (prose, table cells and captions)
  const textOf = (p: Paragraph): React.ReactNode => {
    const ptext = p.text ?? ''
    const segs = segmentsForParagraph(ptext, p.id ?? '', visible, selectedId)
    return segs.map((s, i) => {
      const body = renderPieces(mathPieces(ptext, s.start, s.end, p.math))
      if (s.severity === null) return <span key={i}>{body}</span>
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
              if (!arr.includes(el)) segRefs.current.set(id, [...arr, el])
            }
          }}
          onClick={() => onPick(s.itemIds)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && onPick(s.itemIds)}
        >
          {body}
        </span>
      )
    })
  }

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
                benchLabel(report),
              ],
              ...(report.library
                ? ([
                    [
                      '文献文件夹',
                      `${report.library.links?.length ?? 0} 篇文献连接了本地原文`,
                    ],
                  ] as [string, string][])
                : []),
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
        <div
          className="callout"
          style={{ marginTop: 24, marginBottom: overview ? 16 : 40 }}
        >
          <DocMagnifyIcon size={20} color="var(--accent)" />
          <div className="font-normal">
            {nHigh + nMedium === 0 ? (
              `没有发现严重问题，其余提示${exportWhere}。`
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
                ，{exportWhere}。
              </>
            )}
          </div>
        </div>
        <OverviewCard overview={overview} style={{ marginBottom: 40 }} />
      </div>
      {blocks.map((b) => {
        if (b.kind === 'table')
          return (
            <div key={b.id} className="paper-table-wrap">
              <table className="paper-table">
                <tbody>
                  {b.rows.map((row, r) => (
                    <tr
                      key={r}
                      className={row[0]?.header ? 'head' : undefined}
                    >
                      {row.map((c) => (
                        <td
                          key={c.col}
                          colSpan={c.colspan > 1 ? c.colspan : undefined}
                        >
                          {c.paras.map((p, k) => (
                            <div key={p.id ?? k}>{textOf(p)}</div>
                          ))}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        const p = b.p
        const ptext = p.text ?? ''
        if (title && ptext.trim() === title) return null // shown once above
        const isHeading = headingIds.has(p.id ?? '')
        const isRef = refParaIds.has(p.id ?? '')
        const imgs = (p.images ?? [])
          .map((name) => figureUrl(name))
          .filter(Boolean) as string[]
        if (imgs.length || p.caption)
          return (
            <figure key={p.id} data-pid={p.id} className="paper-fig">
              {imgs.length > 0 && (
                <div className="paper-fig-row">
                  {imgs.map((src) => (
                    <img
                      key={src}
                      src={src}
                      alt=""
                      loading="lazy"
                      draggable={false}
                    />
                  ))}
                </div>
              )}
              {ptext && (
                <figcaption className="t13 secondary">
                  {textOf(p)}
                </figcaption>
              )}
            </figure>
          )
        return (
          <p
            key={p.id}
            data-pid={p.id}
            className={isRef ? 'paper-refs' : undefined}
            style={{
              fontWeight: isHeading ? 600 : 400,
              fontSize: isHeading ? 20 : undefined,
              margin: 0,
              marginTop: isHeading ? 32 : 0,
              marginBottom: 16,
            }}
          >
            {textOf(p)}
          </p>
        )
      })}
    </>
  )
}

/** LaTeX inline math keeps its sub/superscripts in the reading view; the
 *  flattened text stays the anchor coordinate system. */
function renderPieces(pieces: Piece[]): React.ReactNode {
  if (pieces.length === 1 && pieces[0].kind === 'text') return pieces[0].text
  return pieces.map((x, i) =>
    x.kind === 'text' ? (
      x.text
    ) : (
      <span key={i} className="math" title={x.text}>
        {x.runs.map(([t, style], j) =>
          style === 'sub' ? (
            <sub key={j}>{t}</sub>
          ) : style === 'sup' ? (
            <sup key={j}>{t}</sup>
          ) : (
            t
          )
        )}
      </span>
    )
  )
}

function InspectorList({
  items,
  report,
  grouped,
  selectedId,
  onSelect,
  onCollapse,
}: {
  items: ListItem[]
  report: Report
  grouped: boolean
  selectedId: string | null
  onSelect: (id: string) => void
  onCollapse: () => void
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

  const { ref: listScrollRef, fadeClass: listFade } =
    useScrollFade<HTMLDivElement>()

  // 只在报告首次打开时 stagger；之后筛选切换出现的行直接显示
  const [opening, setOpening] = useState(true)
  useEffect(() => {
    const t = setTimeout(() => setOpening(false), 12 * 20 + 160)
    return () => clearTimeout(t)
  }, [])
  let rowIdx = 0
  const row = (i: ListItem) => {
    // staggered entrance — max 12 rows animate, the rest are instant
    const delay = Math.min(rowIdx++, 12) * 20
    const sub = refLine(i, report) ?? firstLine(i.detail)
    return (
      <button
        key={i.id}
        className={`list-row${opening ? ' row-in' : ''} ${i.id === selectedId ? 'sel' : ''}`}
        style={opening ? { animationDelay: `${delay}ms` } : undefined}
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
        className="t17 font-semibold bar-solid-subtle drag-strip flex items-center justify-between"
        style={{ padding: '0 16px', flex: 'none', height: 52 }}
      >
        <span>{items.length} 个问题</span>
        <button
          className="icon-btn"
          aria-label="收起检查器"
          title="收起检查器 ⌘⇧\"
          onClick={onCollapse}
        >
          <SidebarTrailingIcon size={15} />
        </button>
      </div>
      <div
        ref={listScrollRef}
        className={`fade-scroll flex-1 overflow-y-auto flex flex-col gap-1${listFade ? ` ${listFade}` : ''}`}
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
