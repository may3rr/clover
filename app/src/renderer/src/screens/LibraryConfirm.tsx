import { useEffect, useMemo, useState } from 'react'
import { apiJson } from '../lib/api'
import { ChevronDownIcon, SevGlyph } from '../components/Icons'
import { SideIcon, type SideIconName } from '../components/SideIcons'
import {
  baseName,
  counts,
  docLabel,
  exemplarIds,
  finalLinks,
  initialChoice,
  rowState,
  type LibraryScan,
  type LinkChoice,
  type LinkFilter,
} from '../lib/library'
import type { LibraryLink } from '../types/report'

interface Venue {
  id: string
  name: string
  n_papers: number
}

interface Props {
  scan: LibraryScan
  libraryDir: string
  onStart: (opts: { paper: string; links: LibraryLink[]; venue: string }) => void
  onCancel: () => void
  error?: string | null
}

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
 *  选出的标为待确认；作者可以改派或取消，确认后才开始体检。 */
export default function LibraryConfirm({ scan, libraryDir, onStart, onCancel, error }: Props) {
  const [choice, setChoice] = useState<LinkChoice>(() => initialChoice(scan.library))
  const [touched, setTouched] = useState<Set<string>>(new Set())
  // open on the rows worth a look: model picks first, else the links
  const [filter, setFilter] = useState<LinkFilter>(() =>
    (scan.library.links ?? []).some((l) => l.status === 'review')
      ? 'review'
      : (scan.library.links ?? []).length
        ? 'linked'
        : 'all'
  )
  const [venue, setVenue] = useState('')
  const [venues, setVenues] = useState<Venue[]>([])

  useEffect(() => {
    apiJson<Venue[]>('/venues')
      .then(setVenues)
      .catch(() => setVenues([]))
  }, [])

  const docs = scan.library.docs ?? []
  const docById = useMemo(() => new Map(docs.map((d) => [d.id, d])), [docs])
  const c = counts(scan, choice, touched)
  const exemplars = exemplarIds(scan, choice)
  const rows = scan.references.filter(
    (r) => filter === 'all' || rowState(scan, choice, touched, r.id) === filter
  )

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

  const baseline = (() => {
    const b = scan.baseline
    const chosen = venues.find((v) => v.id === venue)
    if (chosen)
      return chosen.n_papers
        ? `按《${chosen.name}》的内置基线对标（${chosen.n_papers} 篇论文）。`
        : `按《${chosen.name}》的投稿要求检查，没有可用的对标基线。`
    if (b.source === 'exemplars' && exemplars.length >= 5)
      return `用文件夹中《${b.name}》的 ${exemplars.length} 篇论文作为对标范文，只在本机统计。`
    if (b.source === 'builtin' || (b.source === 'exemplars' && b.name))
      return `文件夹中的同刊论文不足 5 篇，改用《${b.name}》的内置基线对标。`
    return '没有识别出目标期刊。可以在下面选择目标期刊；不选择时，引用分布与英文语料对比，只比较占比。'
  })()

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
            <div className="t13 secondary">中文期刊对标</div>
            <div className="font-normal">{baseline}</div>
            <label className="pill-quiet flex items-center gap-1" style={{ alignSelf: 'flex-start', marginTop: 4 }}>
              <span className="t13 secondary">目标期刊</span>
              <select
                className="t13"
                style={{ appearance: 'none', background: 'transparent', border: 'none', padding: 0 }}
                value={venue}
                onChange={(e) => setVenue(e.target.value)}
                aria-label="目标期刊"
              >
                <option value="">自动识别</option>
                {venues.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
              <ChevronDownIcon size={13} color="var(--text-secondary)" />
            </label>
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
                venue: venues.find((v) => v.id === venue)?.name ?? '',
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
