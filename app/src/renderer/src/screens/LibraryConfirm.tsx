import { useEffect, useMemo, useState } from 'react'
import { apiFetch, apiJson } from '../lib/api'
import { CheckSquareIcon, ChevronDownIcon, SevGlyph } from '../components/Icons'
import { SideIcon, type SideIconName } from '../components/SideIcons'
import {
  baseName,
  baselineText,
  counts,
  docLabel,
  exemplarCandidates,
  exemplarMeta,
  finalLinks,
  initialChoice,
  MIN_EXEMPLARS,
  pickedExemplars,
  rowState,
  venueState,
  type LibraryScan,
  type LinkChoice,
  type LinkFilter,
  type VenueEntry,
  type VenueState,
} from '../lib/library'
import type { LibraryDoc, LibraryLink } from '../types/report'

interface Props {
  scan: LibraryScan
  libraryDir: string
  onStart: (opts: {
    paper: string
    links: LibraryLink[]
    venue: string
    exemplars: string[]
  }) => void
  onCancel: () => void
  /** the target venue changed here: the home screen keeps the same one */
  onVenueChange?: (venue: string) => void
  error?: string | null
  /** shots: open on the exemplar list */
  initialFilter?: 'exemplars'
}

type Filter = LinkFilter | 'exemplars'

const FILTER_ICON: Record<LinkFilter, SideIconName> = {
  all: 'all',
  review: 'support',
  linked: 'doc',
  none: 'authenticity',
}

const FILTERS: [LinkFilter, string][] = [
  ['all', '全部文献'],
  ['review', '待确认'],
  ['linked', '已连接原文'],
  ['none', '没有原文'],
]

/** 连接确认：参考文献条目 ↔ 文献文件夹里的 PDF。规则连上的直接列出，模型
 *  选出的标为待确认；作者可以改派或取消。目标期刊可以填写或修改，被认作
 *  该刊范文的 PDF 逐篇列出，作者勾选后才开始体检。 */
export default function LibraryConfirm({
  scan,
  libraryDir,
  onStart,
  onCancel,
  onVenueChange,
  error,
  initialFilter,
}: Props) {
  const [choice, setChoice] = useState<LinkChoice>(() => initialChoice(scan.library))
  const [touched, setTouched] = useState<Set<string>>(new Set())
  // open on the rows worth a look: model picks first, else the links
  const [filter, setFilter] = useState<Filter>(() =>
    initialFilter ??
    ((scan.library.links ?? []).some((l) => l.status === 'review')
      ? 'review'
      : (scan.library.links ?? []).length
        ? 'linked'
        : 'all')
  )
  const [venues, setVenues] = useState<VenueEntry[]>([])
  const [vs, setVs] = useState<VenueState>(() => venueState(scan))
  const [picked, setPicked] = useState<Set<string>>(() => new Set(vs.defaultIds))
  const [venueInput, setVenueInput] = useState(vs.venue ?? '')
  const [venueBusy, setVenueBusy] = useState(false)
  const [venueError, setVenueError] = useState<string | null>(null)

  useEffect(() => {
    apiJson<VenueEntry[]>('/venues')
      .then(setVenues)
      .catch(() => setVenues([]))
  }, [])

  const docs = vs.docs
  const docById = useMemo(() => new Map(docs.map((d) => [d.id, d])), [docs])
  const c = counts(scan, choice, touched)
  const exemplars = pickedExemplars(picked, vs, choice)
  const rows = scan.references.filter(
    (r) => filter === 'all' || rowState(scan, choice, touched, r.id) === filter
  )
  // journals to offer: the registry's and those printed on the folder's PDFs
  const venueOptions = useMemo(
    () => [...new Set([...venues.map((v) => v.name), ...docs.map((d) => d.venue ?? '')])].filter(Boolean),
    [venues, docs]
  )

  const applyVenue = async (raw: string) => {
    const name = raw.trim()
    if (name === (vs.venue ?? '')) return
    setVenueBusy(true)
    setVenueError(null)
    try {
      const fd = new FormData()
      fd.append('library', libraryDir)
      fd.append('venue', name)
      fd.append('linked', JSON.stringify(Object.values(choice).filter(Boolean)))
      fd.append('paper_type', scan.paper_type ?? 'research')
      const res = await apiFetch('/library/venue', { method: 'POST', body: fd })
      if (!res.ok) throw new Error(String(res.status))
      const r = (await res.json()) as {
        entry: VenueEntry | null
        library: {
          venue: string | null
          venue_source: VenueState['source']
          venue_match_ids: string[]
          exemplar_ids: string[]
          docs: LibraryDoc[]
        }
      }
      const next: VenueState = {
        venue: r.library.venue,
        source: r.library.venue_source,
        matchIds: r.library.venue_match_ids,
        defaultIds: r.library.exemplar_ids,
        docs: r.library.docs,
        entry: r.entry,
      }
      setVs(next)
      setPicked(new Set(next.defaultIds))
      setVenueInput(next.venue ?? '')
      onVenueChange?.(next.venue ?? '')
    } catch {
      setVenueError('无法更新目标期刊。请确认文献文件夹还在原处，然后重新填写。')
    } finally {
      setVenueBusy(false)
    }
  }

  const togglePick = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const pick = (refId: string, docId: string) => {
    setChoice((prev) => {
      const next = { ...prev }
      // one PDF serves one entry: taking it releases the previous owner
      for (const [k, v] of Object.entries(next)) if (docId && v === docId) next[k] = ''
      next[refId] = docId
      return next
    })
    setTouched((t) => new Set(t).add(refId))
  }

  const confirmAll = () => setTouched(new Set(scan.references.map((r) => r.id)))

  const baseline = baselineText(vs, exemplars.length)

  return (
    <div className="relative h-full overflow-hidden">
      {/* ---------- sidebar: filters ---------- */}
      <aside className="glass-sidebar flex flex-col">
        <div className="drag-strip" style={{ height: 52, flex: 'none' }} />
        <div className="group-label" style={{ fontWeight: 600 }}>
          文献连接
        </div>
        <nav className="flex flex-col" style={{ padding: '0 8px' }}>
          {FILTERS.map(([key, label]) => {
            const n =
              key === 'all'
                ? scan.references.length
                : key === 'review'
                  ? c.review
                  : key === 'linked'
                    ? c.linked
                    : c.none
            return (
              <button
                key={key}
                className={`side-row ${filter === key ? 'sel' : ''}`}
                style={{ fontWeight: filter === key ? 600 : 400 }}
                onClick={() => setFilter(key)}
              >
                <SideIcon name={FILTER_ICON[key]} />
                <span className="flex-1 text-left">{label}</span>
                <span className={`t13 ${key === 'review' && n > 0 ? 'sem-medium' : 'secondary'}`}>{n}</span>
              </button>
            )
          })}
        </nav>
        <div className="group-label" style={{ marginTop: 16 }}>
          期刊对标
        </div>
        <nav className="flex flex-col" style={{ padding: '0 8px' }}>
          <button
            className={`side-row ${filter === 'exemplars' ? 'sel' : ''}`}
            style={{ fontWeight: filter === 'exemplars' ? 600 : 400 }}
            onClick={() => setFilter('exemplars')}
          >
            <SideIcon name="distribution" />
            <span className="flex-1 text-left">对标范文</span>
            <span className="t13 secondary">{exemplars.length}</span>
          </button>
        </nav>
        <div className="flex-1" />
        <div style={{ padding: '0 8px 12px' }}>
          <button className="side-row" onClick={onCancel}>
            <SideIcon name="plus" />
            <span className="flex-1 text-left">检查另一篇</span>
          </button>
        </div>
      </aside>

      {/* ---------- center: reference list ---------- */}
      <div className="flex flex-col h-full" style={{ marginLeft: 240, marginRight: 380, background: 'var(--bg)' }}>
        <div className="drag-strip" style={{ height: 52, flex: 'none' }} />
        <main className="paper flex-1 overflow-y-auto">
          {filter === 'exemplars' ? (
            <ExemplarList
              vs={vs}
              candidates={exemplarCandidates(vs, choice)}
              picked={picked}
              nPicked={exemplars.length}
              onToggle={togglePick}
              onReset={() => setPicked(new Set(vs.defaultIds))}
            />
          ) : (
          <div style={{ maxWidth: 720, margin: '0 auto', padding: '0 48px 48px' }}>
            <div className="t26" style={{ fontWeight: 600 }}>
              核对文献连接
            </div>
            <div className="secondary" style={{ marginTop: 8 }}>
              {scan.references.length} 条参考文献中，{c.linked + c.review} 条在文献文件夹里找到了原文。
              连上的文献用本地原文判断论断支持度、核对题录，其余照常联网核验。
            </div>
            {c.review > 0 && (
              <div className="callout" style={{ marginTop: 16 }}>
                <SevGlyph severity="medium" size={20} />
                <div className="font-normal flex-1">
                  有 <span className="font-semibold sem-medium">{c.review}</span>{' '}
                  条连接由模型从相近的候选中选出，请逐条确认。
                </div>
                <button className="pill-quiet font-normal" onClick={confirmAll}>
                  全部确认
                </button>
              </div>
            )}
            <div className="flex flex-col" style={{ marginTop: 24, gap: 4 }}>
              {rows.map((r) => {
                const st = rowState(scan, choice, touched, r.id)
                const doc = choice[r.id] ? docById.get(choice[r.id]) : undefined
                return (
                  <div key={r.id} className="list-row flex items-start gap-3">
                    <span className="t13 secondary" style={{ minWidth: 32, paddingTop: 2 }}>
                      {r.label ? `[${r.label}]` : ''}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="font-normal" style={{ wordBreak: 'break-word' }}>
                        {r.title || r.raw}
                      </div>
                      <div className="t13 secondary flex items-center gap-2" style={{ marginTop: 4 }}>
                        {st === 'review' && <SevGlyph severity="medium" size={13} />}
                        <span style={{ wordBreak: 'break-all' }}>
                          {doc
                            ? `${st === 'review' ? '待确认：' : ''}${doc.filename}`
                            : '没有原文 PDF，联网核验'}
                        </span>
                      </div>
                    </div>
                    <label
                      className={`pill-quiet row-action flex items-center gap-1${st === 'review' ? ' keep' : ''}`}
                      style={{ flex: 'none', maxWidth: 160 }}
                    >
                      <select
                        className="t13"
                        style={{ appearance: 'none', background: 'transparent', border: 'none', padding: 0, maxWidth: 120 }}
                        value={choice[r.id] ?? ''}
                        onChange={(e) => pick(r.id, e.target.value)}
                        aria-label={`为 ${r.label ?? r.id} 选择原文`}
                      >
                        <option value="">不连接</option>
                        {docs
                          .filter((d) => d.readable !== false)
                          .map((d) => (
                            <option key={d.id} value={d.id}>
                              {docLabel(d)}
                            </option>
                          ))}
                      </select>
                      <ChevronDownIcon size={13} color="var(--text-secondary)" />
                    </label>
                  </div>
                )
              })}
              {rows.length === 0 && (
                <div className="secondary" style={{ padding: '24px 12px' }}>
                  这一类没有文献。
                </div>
              )}
            </div>
          </div>
          )}
        </main>
      </div>

      {/* ---------- inspector: summary + start ---------- */}
      <aside className="inspector">
        <div className="drag-strip" style={{ height: 52, flex: 'none' }} />
        <div className="flex-1 overflow-y-auto flex flex-col" style={{ padding: '0 16px 16px', gap: 12 }}>
          <div className="card flex flex-col" style={{ gap: 12 }}>
            <div>
              <div className="t13 secondary">论文</div>
              <div className="font-normal" style={{ wordBreak: 'break-all' }}>{baseName(scan.paper)}</div>
            </div>
            <div>
              <div className="t13 secondary">文献文件夹</div>
              <div className="font-normal" style={{ wordBreak: 'break-all' }}>
                {baseName(libraryDir)}，{docs.length} 个 PDF
              </div>
            </div>
          </div>
          <div className="card flex flex-col" style={{ gap: 8 }}>
            <label className="t13 secondary" htmlFor="target-venue">
              目标期刊或会议
            </label>
            <input
              id="target-venue"
              className="field-input"
              list="venue-options"
              placeholder="留空不对标"
              value={venueInput}
              disabled={venueBusy}
              onChange={(e) => setVenueInput(e.target.value)}
              onBlur={(e) => applyVenue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') applyVenue((e.target as HTMLInputElement).value)
              }}
            />
            <datalist id="venue-options">
              {venueOptions.map((v) => (
                <option key={v} value={v} />
              ))}
            </datalist>
            <div className="font-normal">{venueError ?? baseline}</div>
            {filter !== 'exemplars' && (
              <button
                className="pill-quiet font-normal"
                style={{ alignSelf: 'flex-start' }}
                onClick={() => setFilter('exemplars')}
              >
                核对对标范文
              </button>
            )}
          </div>
          {(scan.library.unsupported ?? []).length > 0 && (
            <div className="card t13 secondary">
              有 {scan.library.unsupported!.length} 个 CAJ 文件没有读取。请在知网下载这些文献的 PDF 版本，放进文献文件夹后重新拖入。
            </div>
          )}
          {docs.some((d) => d.readable === false) && (
            <div className="card t13 secondary">
              {docs.filter((d) => d.readable === false).length} 个 PDF 是扫描件或无法读取文字，没有参与连接。
            </div>
          )}
          {scan.candidates.length > 0 && (
            <div className="card t13 secondary">
              文件夹根目录还有 {scan.candidates.map(baseName).join('、')}，这次检查的是最近修改的 {baseName(scan.paper)}。
            </div>
          )}
        </div>
        <div style={{ padding: 16 }}>
          {error && (
            <div className="t13" style={{ marginBottom: 12 }}>
              {error}
            </div>
          )}
          <button
            className="pill-accent"
            style={{ width: '100%', justifyContent: 'center' }}
            onClick={() =>
              onStart({
                paper: scan.paper,
                links: finalLinks(scan, choice),
                venue: vs.venue ?? '',
                exemplars,
              })
            }
          >
            开始体检
          </button>
        </div>
      </aside>
    </div>
  )
}

/** 对标范文：未被引用的 PDF 逐篇列出，识别为目标期刊的在前。勾选的
 *  论文不少于 5 篇时，用作本次体检的对标基线。 */
function ExemplarList({
  vs,
  candidates,
  picked,
  nPicked,
  onToggle,
  onReset,
}: {
  vs: VenueState
  candidates: LibraryDoc[]
  picked: Set<string>
  nPicked: number
  onToggle: (id: string) => void
  onReset: () => void
}) {
  const match = new Set(vs.matchIds)
  const mine = candidates.filter((d) => match.has(d.id))
  const others = candidates.filter((d) => !match.has(d.id))
  const v = vs.venue ? `《${vs.venue}》` : '目标期刊'
  const row = (d: LibraryDoc) => {
    const on = picked.has(d.id)
    return (
      <button
        key={d.id}
        role="checkbox"
        aria-checked={on}
        className="list-row flex items-start gap-3"
        onClick={() => onToggle(d.id)}
      >
        <span style={{ paddingTop: 2 }}>
          <CheckSquareIcon size={18} on={on} />
        </span>
        <span className="flex-1 min-w-0">
          <span className="font-normal block" style={{ wordBreak: 'break-word' }}>
            {d.title || d.filename}
          </span>
          <span className="t13 secondary block" style={{ marginTop: 4 }}>
            {exemplarMeta(d)}
          </span>
        </span>
      </button>
    )
  }
  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '0 48px 48px' }}>
      <div className="t26" style={{ fontWeight: 600 }}>
        核对对标范文
      </div>
      <div className="secondary" style={{ marginTop: 8 }}>
        这里列出文件夹中没有被引用的论文。勾选的论文和参考文献里的{v}论文一起作为范文，
        逐篇统计章节结构、引用分布、参考文献构成和研究要素，再与本文比较。默认选中识别为该刊、且与本文类型相同的论文。
      </div>
      <div className="callout" style={{ marginTop: 16 }}>
        <div className="font-normal flex-1">
          已选 <span className="font-semibold">{nPicked}</span> 篇，连同参考文献里的该刊论文合计不少于{' '}
          {MIN_EXEMPLARS} 篇才对标。
        </div>
        <button className="pill-quiet font-normal" onClick={onReset}>
          恢复默认选择
        </button>
      </div>
      {mine.length > 0 && (
        <>
          <div className="group-label" style={{ marginTop: 24, padding: '0 12px' }}>
            识别为{v}的论文
          </div>
          <div className="flex flex-col" style={{ gap: 4 }}>
            {mine.map(row)}
          </div>
        </>
      )}
      {others.length > 0 && (
        <>
          <div className="group-label" style={{ marginTop: 24, padding: '0 12px' }}>
            其他未被引用的 PDF
          </div>
          <div className="flex flex-col" style={{ gap: 4 }}>
            {others.map(row)}
          </div>
        </>
      )}
      {candidates.length === 0 && (
        <div className="secondary" style={{ padding: '24px 12px' }}>
          文献文件夹里的 PDF 都已连到参考文献。把目标期刊近期发表的论文放进文献文件夹，然后重新拖入。
        </div>
      )}
    </div>
  )
}
