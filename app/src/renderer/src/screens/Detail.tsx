import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Report, RefCheck, SectionDist } from '../types/report'
import type { ListItem } from '../lib/items'
import { supportForFinding } from '../lib/claims'
import { barGeom, comparedSections } from '../lib/dist'
import { ChevronDownIcon, ChevronLeftIcon, SidebarTrailingIcon } from '../components/Icons'
import { formatLoc } from '../lib/accept'
import { HL_CLASS } from '../lib/highlight'
import {
  boolSummary,
  exemplarRows,
  fmtMetric,
  GROUP_LABEL,
  groupedMetrics,
  metricsFor,
} from '../lib/venue'
import type { ExemplarInfo, VenueMetric } from '../types/report'

interface Props {
  item: ListItem
  report: Report
  backLabel: string
  onBack: () => void
  onCollapse: () => void
  /** scroll the paper to a paragraph (venue measures point at several) */
  onJump?: (paragraphId: string) => void
}

export default function Detail({ item, report, backLabel, onBack, onCollapse, onJump }: Props) {
  return (
    <div className="detail-in flex flex-col flex-1 min-h-0" key={item.id}>
      <div
        className="drag-strip flex items-center justify-between"
        style={{ height: 52, flex: 'none', padding: '0 16px' }}
      >
        <button
          className="link-accent flex items-center gap-1"
          onClick={onBack}
        >
          <ChevronLeftIcon size={15} />
          {backLabel}
        </button>
        <button
          className="icon-btn"
          aria-label="收起检查器"
          title="收起检查器 ⌘⇧\"
          onClick={onCollapse}
        >
          <SidebarTrailingIcon size={15} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        <div style={{ padding: '0 16px 16px' }}>
          <div className="font-semibold detail-title" style={{ fontSize: 17 }}>
            {item.title}
          </div>
          {formatLoc(item.anchors[0]?.loc) && (
            <div className="t13 secondary" style={{ marginTop: 4 }}>
              源码位置 {formatLoc(item.anchors[0]?.loc)}
            </div>
          )}
          <div
            className="flex flex-col"
            style={{ gap: 12, marginTop: 16 }}
          >
            {/* the why comes first; the evidence below backs it up */}
            <DetailLines detail={item.detail} />
            <SourceSnippet item={item} />
            {item.kind === 'group' && item.layer === 'distribution' ? (
              <DistributionDetail item={item} report={report} onJump={onJump} />
            ) : item.kind === 'group' ? (
              <ReorderDetail item={item} report={report} />
            ) : item.kind === 'revision' ? (
              <RevisionDetail
                item={item}
                tex={report.document.source_format === 'tex'}
              />
            ) : (
              <FindingDetail item={item} report={report} onJump={onJump} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/** LaTeX reports: the source line(s) behind the anchor, with the
 *  anchored text tinted — what the author will actually edit. */
function SourceSnippet({ item }: { item: ListItem }) {
  const a = item.anchors[0]
  if (!a?.snippet) return null
  const text = a.snippet
  // generated from a tuple schema: [start, end] within the snippet
  const hl = a.snippet_hl as [number, number] | null | undefined
  const tint = HL_CLASS[item.severity]
  return (
    <div className="src-snippet t13">
      {hl ? (
        <>
          {text.slice(0, hl[0])}
          <span className={`hl ${tint}`}>{text.slice(hl[0], hl[1])}</span>
          {text.slice(hl[1])}
        </>
      ) : (
        text
      )}
    </div>
  )
}

function DetailLines({ detail }: { detail: string }) {
  const lines = detail.split('\n').filter(Boolean)
  if (!lines.length) return null
  return (
    <div className="flex flex-col gap-2">
      {lines.map((l, i) => (
        <div key={i} className="font-normal">
          {l}
        </div>
      ))}
    </div>
  )
}

function anchoredText(report: Report, item: ListItem): string | null {
  const a = item.anchors[0]
  if (!a) return null
  const p = (report.paragraphs ?? []).find((x) => x.id === a.paragraph_id)
  if (!p?.text) return null
  return p.text.slice(a.start, a.end)
}

// ------------------------------------------------------------- support

function FindingDetail({
  item,
  report,
  onJump,
}: {
  item: ListItem
  report: Report
  onJump?: (paragraphId: string) => void
}) {
  if (item.layer === 'support')
    return <SupportDetail item={item} report={report} />
  if (item.layer === 'authenticity')
    return <AuthenticityDetail item={item} report={report} />
  if (item.layer === 'distribution')
    return <DistributionDetail item={item} report={report} onJump={onJump} />
  return <NormsDetail item={item} report={report} />
}

function SupportDetail({ item, report }: { item: ListItem; report: Report }) {
  const s = supportForFinding(report, item)
  return (
    <>
      {s.sentence && (
        <div className="card">
          <div className="t13 secondary" style={{ marginBottom: 8 }}>
            你的论文写道
          </div>
          <div className="font-normal">
            <ClaimInSentence sentence={s.sentence} claim={s.claim?.text} />
          </div>
        </div>
      )}
      {s.excerpt && (
        <div className="card">
          <div className="t13 secondary" style={{ marginBottom: 8 }}>
            被引文献原文
          </div>
          {s.sourceTitle && (
            <div className="font-semibold" style={{ marginBottom: 4 }}>
              {s.sourceTitle}
            </div>
          )}
          <Excerpt
            text={s.excerpt}
            span={s.evidenceSpan}
            label={s.label}
          />
          <div className="t13 secondary" style={{ marginTop: 8 }}>
            {sourceLine(s.sourceKind, s.sourceFile, s.sourcePage)}
          </div>
        </div>
      )}
    </>
  )
}

/** where the excerpt came from: the user's own PDF (with the page the
 *  evidence sits on), an open-access full text, or the abstract */
export function sourceLine(
  kind: string | null,
  file: string | null | undefined,
  page: number | null | undefined
): string {
  if (file) return `依据文献文件夹中的本地原文 ${file}${page ? `，第 ${page} 页` : ''}`
  return kind === 'fulltext' ? '依据开放全文' : '依据摘要'
}

/** the sentence with the judged claim set in semibold — claim offsets
 * are paragraph-relative, so locate the claim text in the sentence */
function ClaimInSentence({ sentence, claim }: { sentence: string; claim?: string | null }) {
  const i = claim ? sentence.indexOf(claim) : -1
  if (!claim || i < 0) return <>{sentence}</>
  return (
    <>
      {sentence.slice(0, i)}
      <span className="font-semibold">{claim}</span>
      {sentence.slice(i + claim.length)}
    </>
  )
}

/** sentence boundaries [start, end) — split after ., !, ? + whitespace */
function sentenceRanges(text: string): [number, number][] {
  const out: [number, number][] = []
  let s = 0
  const re = /[.!?]['"”’)\]]?\s+/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (m.index + m[0].length > s) {
      out.push([s, m.index + m[0].length])
      s = m.index + m[0].length
    }
  }
  if (s < text.length) out.push([s, text.length])
  return out
}

/** Source excerpt: collapsed to the evidence sentence ±1 with "…" ends
 * (or the first 3 sentences when there is no evidence); a text button
 * expands to the full excerpt with a 240ms height tween. */
function Excerpt({
  text,
  span,
  label,
}: {
  text: string
  span: [number, number] | null
  label: string | null
}) {
  const [open, setOpen] = useState(false)
  const innerRef = useRef<HTMLDivElement>(null)
  const [h, setH] = useState<number>()

  const hasSpan =
    !!span && span[0] < span[1] && span[1] <= text.length
  const { cutS, cutE } = useMemo(() => {
    const sents = sentenceRanges(text)
    if (!sents.length) return { cutS: 0, cutE: text.length }
    let lo = 0
    let hi = sents.length - 1
    if (hasSpan && span) {
      const i0 = sents.findIndex(([, e]) => span[0] < e)
      const i1 = sents.findIndex(([, e]) => span[1] <= e)
      lo = Math.max(0, (i0 === -1 ? sents.length - 1 : i0) - 1)
      hi = Math.min(
        sents.length - 1,
        (i1 === -1 ? sents.length - 1 : i1) + 1
      )
    } else {
      hi = Math.min(sents.length - 1, 2)
    }
    return { cutS: sents[lo][0], cutE: sents[hi][1] }
  }, [text, hasSpan, span])

  const trimmed = cutS > 0 || cutE < text.length
  const shown = open || !trimmed ? [0, text.length] : [cutS, cutE]
  const slice = text.slice(shown[0], shown[1])
  const rel: [number, number] | null =
    hasSpan && span
      ? [
          Math.max(0, span[0] - shown[0]),
          Math.min(slice.length, span[1] - shown[0]),
        ]
      : null
  const valid = rel && rel[0] < rel[1] ? rel : null

  // measure content height after each toggle for the expand animation
  useLayoutEffect(() => {
    const el = innerRef.current
    if (el) setH(el.scrollHeight)
  }, [open, slice])

  const cls =
    label === 'supported'
      ? 'hl-rev'
      : label === 'partial'
        ? 'hl-medium'
        : label === 'unsupported'
          ? 'hl-high'
          : 'hl-low'

  return (
    <>
      <div
        className="excerpt-clip"
        style={h !== undefined ? { height: h } : undefined}
      >
        <div className="font-normal excerpt-swap" key={String(open)} ref={innerRef}>
          {!open && shown[0] > 0 && '… '}
          {valid ? (
            <>
              {slice.slice(0, valid[0])}
              <span className={`hl ${cls}`}>
                {slice.slice(valid[0], valid[1])}
              </span>
              {slice.slice(valid[1])}
            </>
          ) : (
            slice
          )}
          {!open && shown[1] < text.length && ' …'}
        </div>
      </div>
      {trimmed && (
        <button
          className="link-accent t13 font-normal"
          style={{ marginTop: 8 }}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? '收起' : '显示完整片段'}
        </button>
      )}
    </>
  )
}

// -------------------------------------------------------- authenticity

function AuthenticityDetail({
  item,
  report,
}: {
  item: ListItem
  report: Report
}) {
  const f = item.finding
  const refId = f?.refs?.[0]
  const ref = (report.references ?? []).find((r) => r.id === refId)
  const check: RefCheck | undefined = (report.ref_checks ?? []).find(
    (c) => c.ref_id === refId
  )
  const matched = check?.matched as Record<string, unknown> | undefined

  type Row = [string, string, string | null, boolean]
  // the entry disagrees with the user's own PDF rather than a database
  const localMode = (check?.issues ?? []).some((i) => i.includes('本地原文'))
  const theirs = (k: string): string | null => {
    if (!matched) return null
    const v = matched[localMode ? `local_${k}` : k]
    if (v == null) return null
    if (Array.isArray(v)) return v.slice(0, 4).join(', ')
    return String(v)
  }
  const flag = (k: string) => (check?.issues ?? []).some((i) => i.includes(k))

  const rows: Row[] = [
    ['标题', ref?.title ?? '', theirs('title'), flag('标题')],
    [
      '作者',
      (ref?.authors ?? []).join(', '),
      theirs('authors'),
      flag('首作者') || flag('作者'),
    ],
    ['年份', ref?.year ? String(ref.year) : '', theirs('year'), flag('年份')],
    ['出处', ref?.venue ?? '', theirs('venue'), flag('出处') || flag('期刊')],
    ['DOI', ref?.doi ?? '', theirs('doi'), flag('DOI')],
  ]

  const SOURCE_NAMES: Record<string, string> = {
    s2: 'Semantic Scholar',
    crossref: 'Crossref',
    openalex: 'OpenAlex',
    arxiv: 'arXiv',
  }
  const rawSrc = matched?.source ? String(matched.source) : ''
  const srcName = SOURCE_NAMES[rawSrc.toLowerCase()] ?? rawSrc
  const doiUrl = matched?.doi
    ? `https://doi.org/${String(matched.doi).replace(/^https?:\/\/doi.org\//, '')}`
    : ref?.doi
      ? `https://doi.org/${ref.doi.replace(/^https?:\/\/doi.org\//, '')}`
      : null

  const localFile = matched?.local_file ? String(matched.local_file) : null
  const status = localMode
    ? `与文献文件夹中的本地原文 ${localFile ?? ''} 不一致，不一致的字段已标出`
    : check?.status === 'not_found'
      ? '检索的文献数据库中均未找到这篇文献'
      : !matched
        ? '暂时无法完成核验，下面是你写的条目'
        : `已在 ${srcName || '数据库'} 找到对应记录${
            rows.some((r) => r[3]) ? '，不一致的字段已标出' : ''
          }`

  return (
    <>
      <div className="card">
        <div className="t13 secondary" style={{ marginBottom: 12 }}>
          {status}
        </div>
        <div className="flex flex-col" style={{ gap: 12 }}>
          {rows.map(([label, yours, theirs, bad]) => (
            <FieldRow
              key={label}
              label={label}
              value={yours}
              theirs={matched && bad ? theirs ?? '—' : null}
              bad={!!matched && bad}
              source={localMode ? '本地原文' : '数据库记录'}
            />
          ))}
        </div>
      </div>
      {doiUrl && (
        <button
          className="link-accent font-normal t13"
          style={{ textAlign: 'left', wordBreak: 'break-all' }}
          onClick={() => window.citecheck.openExternal(doiUrl)}
        >
          在 doi.org 打开
        </button>
      )}
    </>
  )
}

/** one bibliographic field: what the paper says, and — only where it
 * disagrees — what the database has, directly beneath it */
function FieldRow({
  label,
  value,
  theirs,
  bad,
  source = '数据库记录',
}: {
  label: string
  value: string
  theirs: string | null
  bad: boolean
  source?: string
}) {
  return (
    <div className="min-w-0">
      <div className="t13 secondary" style={{ marginBottom: 4 }}>
        {label}
      </div>
      <div className="font-normal" style={{ wordBreak: 'break-word' }}>
        <span className={bad ? 'hl hl-high' : undefined}>{value || '—'}</span>
      </div>
      {theirs != null && (
        <div className="t13" style={{ marginTop: 4, wordBreak: 'break-word' }}>
          <span className="secondary" style={{ marginRight: 8 }}>
            {source}
          </span>
          {theirs}
        </div>
      )}
    </div>
  )
}

// -------------------------------------------------------- distribution

function DistributionDetail({
  item,
  report,
  onJump,
}: {
  item: ListItem
  report: Report
  onJump?: (paragraphId: string) => void
}) {
  const d = report.distribution
  // exemplar baselines: every measure behind the finding, paper by paper
  const keys =
    item.kind === 'group'
      ? (item.findings ?? []).flatMap((f) => f.metrics ?? [])
      : (item.finding?.metrics ?? [])
  if (keys.length && metricsFor(d, keys).length)
    return <VenueMetricsDetail keys={keys} report={report} onJump={onJump} />
  const secs = d ? comparedSections(d) : []
  // a single section finding zooms to its section; the collapsed group
  // shows every compared section together
  const only = item.kind === 'group' ? undefined : item.anchors[0]?.paragraph_id
  const shown = only
    ? secs.filter((s) => {
        const sec = (report.sections ?? []).find((x) => x.id === s.section_id)
        return sec?.heading_paragraph_id === only
      })
    : secs
  const rows = shown.length ? shown : secs
  const venueStats = (d?.venue_stats ?? []).filter((v) => v.bench)
  if (item.kind !== 'group' && !item.anchors.length && venueStats.length) {
    return (
      <>
        <div className="t13 secondary">
          {d?.venue_source === 'exemplars'
            ? `对标文献文件夹中《${d.venue}》的 ${d.n_papers} 篇论文，只在本机统计。`
            : `对标内置的《${d?.venue}》基线，共 ${d?.n_papers ?? 0} 篇论文。`}
        </div>
        <div className="card flex flex-col" style={{ gap: 16 }}>
          {venueStats.map((v) => (
            <MetricGroup
              key={v.key}
              label={v.label}
              value={v.value ?? 0}
              bench={v.bench ?? null}
              fmt={(x) => (v.unit === '%' ? `${(x * 100).toFixed(0)}%` : `${x.toFixed(0)} ${v.unit}`)}
            />
          ))}
        </div>
      </>
    )
  }
  return (
    <>
      {d?.note && <div className="t13 secondary">{d.note}</div>}
      <div className="card flex flex-col" style={{ gap: 16 }}>
        {rows.map((s) => (
          <DistRow key={s.section_id} s={s} />
        ))}
      </div>
    </>
  )
}

function DistRow({ s }: { s: SectionDist }) {
  const comparable = s.density_flag !== 'na'
  return (
    <div>
      <div className="font-semibold" style={{ marginBottom: 4 }}>
        {s.title || '全文'}
      </div>
      <MetricGroup
        label="引用占比"
        value={s.share ?? 0}
        bench={s.bench_share ?? null}
        fmt={(x) => `${(x * 100).toFixed(1)}%`}
      />
      {comparable ? (
        <MetricGroup
          label="每千词引用"
          value={s.density ?? 0}
          bench={s.bench_density ?? null}
          fmt={(x) => x.toFixed(1)}
        />
      ) : (
        <div className="t13 secondary" style={{ marginTop: 8 }}>
          密度不可比（语言不同）
        </div>
      )}
    </div>
  )
}

/** one metric: "本文" bar + "领域常见范围" band on a shared 0..max axis,
 * end values in 13px secondary, labels like "本文 13.0%" / "常见 4.8%–14.7%" */
function MetricGroup({
  label,
  value,
  bench,
  fmt,
}: {
  label: string
  value: number
  bench: { q1?: number | null; q3?: number | null; median?: number | null } | null
  fmt: (x: number) => string
}) {
  const g = barGeom(value, bench)
  const track = (children: React.ReactNode) => (
    <div
      className="relative"
      style={{ flex: 1, height: 8, background: 'var(--fill)', borderRadius: 4 }}
    >
      {children}
    </div>
  )
  const val = (t: string) => (
    <span className="t13 secondary" style={{ minWidth: 104 }}>
      {t}
    </span>
  )
  return (
    <div style={{ marginTop: 8 }}>
      <div className="t13 secondary">{label}</div>
      <div className="flex items-center gap-2" style={{ marginTop: 6 }}>
        {track(
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              width: `${g.valueFrac * 100}%`,
              background: 'var(--accent)',
              borderRadius: 4,
            }}
          />
        )}
        {val(`本文 ${fmt(value)}`)}
      </div>
      {bench && (
        <div className="flex items-center gap-2" style={{ marginTop: 4 }}>
          {track(
            <>
              <div
                style={{
                  position: 'absolute',
                  left: `${g.q1 * 100}%`,
                  width: `${Math.max(g.q3 - g.q1, 0.01) * 100}%`,
                  top: 0,
                  bottom: 0,
                  background:
                    'color-mix(in srgb, var(--accent) 30%, transparent)',
                  borderRadius: 4,
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: `${g.median * 100}%`,
                  width: 2,
                  top: -2,
                  bottom: -2,
                  background: 'var(--accent)',
                }}
              />
            </>
          )}
          {val(`常见 ${fmt(bench.q1 ?? 0)}–${fmt(bench.q3 ?? 0)}`)}
        </div>
      )}
      {/* shared axis ends, aligned to the track column */}
      <div className="flex items-center gap-2" style={{ marginTop: 2 }}>
        <div className="flex justify-between" style={{ flex: 1 }}>
          <span className="t13 secondary">0</span>
          <span className="t13 secondary">{fmt(g.max)}</span>
        </div>
        <span style={{ minWidth: 104 }} />
      </div>
    </div>
  )
}

// ---------------------------------------------------- venue exemplars

function VenueMetricsDetail({
  keys,
  report,
  onJump,
}: {
  keys: string[]
  report: Report
  onJump?: (paragraphId: string) => void
}) {
  const d = report.distribution
  const [all, setAll] = useState(false)
  const infos = d?.exemplars ?? []
  const near = infos.filter((e) => e.similar).map((e) => `《${e.title || e.filename}》`)
  const metrics = metricsFor(d, keys)
  const shown = new Set(metrics.map((m) => m.key))
  return (
    <>
      <div className="t13 secondary">
        对标文献文件夹中《{d?.venue}》的 {d?.n_papers ?? 0} 篇论文，每项可以展开查看各篇范文的取值和出处。
        {near.length > 0 && `主题最接近本文的是${near.join('、')}。`}
      </div>
      <div className="card flex flex-col" style={{ gap: 16 }}>
        {metrics.map((m, i) => (
          // the first measure opens on its exemplars: provenance at a glance
          <VenueMetricRow key={m.key} m={m} infos={infos} onJump={onJump} defaultOpen={i === 0} />
        ))}
      </div>
      <button
        className="link-accent flex items-center gap-1"
        style={{ alignSelf: 'flex-start' }}
        aria-expanded={all}
        onClick={() => setAll(!all)}
      >
        {all ? '收起其他对标指标' : '查看其他对标指标'}
        <span style={{ transform: all ? 'rotate(180deg)' : undefined, display: 'flex' }}>
          <ChevronDownIcon size={13} />
        </span>
      </button>
      {all &&
        groupedMetrics(d).map(([g, list]) => {
          const rest = list.filter((m) => !shown.has(m.key))
          if (!rest.length) return null
          return (
            <div key={g} className="flex flex-col" style={{ gap: 8 }}>
              <div className="t13 secondary">{GROUP_LABEL[g]}</div>
              <div className="card flex flex-col" style={{ gap: 16 }}>
                {rest.map((m) => (
                  <VenueMetricRow key={m.key} m={m} infos={infos} onJump={onJump} />
                ))}
              </div>
            </div>
          )
        })}
    </>
  )
}

function VenueMetricRow({
  m,
  infos,
  onJump,
  defaultOpen = false,
}: {
  m: VenueMetric
  infos: ExemplarInfo[]
  onJump?: (paragraphId: string) => void
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [next, setNext] = useState(0)
  const anchors = m.anchors ?? []
  const rows = exemplarRows(m, infos)
  const fmt = (x: number) => fmtMetric(m, x)
  return (
    <div>
      {m.kind === 'bool' ? (
        <>
          <div className="t13 secondary">{m.label}</div>
          <div className="font-normal" style={{ marginTop: 4 }}>
            {boolSummary(m)}
          </div>
        </>
      ) : m.value === null || m.value === undefined ? (
        <>
          <div className="t13 secondary">{m.label}</div>
          <div className="font-normal" style={{ marginTop: 4 }}>
            本文无法判断
            {m.bench && `，范文常见 ${fmt(m.bench.q1)} 至 ${fmt(m.bench.q3)}`}
          </div>
        </>
      ) : (
        <MetricGroup label={m.label} value={m.value} bench={m.bench ?? null} fmt={fmt} />
      )}
      {m.quote && (
        <div className="t13 secondary" style={{ marginTop: 8 }}>
          本文依据：{m.quote}
        </div>
      )}
      <div className="flex items-center flex-wrap" style={{ gap: 12, marginTop: 8 }}>
        {anchors.length > 0 && onJump && (
          <button
            className="link-accent t13"
            onClick={() => {
              onJump(anchors[next % anchors.length].paragraph_id)
              setNext(next + 1)
            }}
          >
            {anchors.length > 1
              ? `在正文中查看第 ${(next % anchors.length) + 1} 处，共 ${anchors.length} 处`
              : '在正文中查看'}
          </button>
        )}
        {rows.length > 0 && (
          <button
            className="link-accent t13 flex items-center gap-1"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {open ? '收起各篇范文' : `查看 ${rows.length} 篇范文的取值`}
            <span style={{ transform: open ? 'rotate(180deg)' : undefined, display: 'flex' }}>
              <ChevronDownIcon size={13} />
            </span>
          </button>
        )}
      </div>
      {open && (
        <div className="flex flex-col" style={{ gap: 8, marginTop: 8 }}>
          {rows.map(({ value, info }) => (
            <div key={value.doc_id} className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="t13" style={{ wordBreak: 'break-word' }}>
                  {info?.title || info?.filename || value.doc_id}
                </div>
                <div className="t13 secondary" style={{ wordBreak: 'break-word' }}>
                  {[
                    info?.similar ? '主题接近' : '',
                    value.page ? `第 ${value.page} 页` : '',
                    value.quote ?? '',
                  ]
                    .filter(Boolean)
                    .join('，')}
                </div>
              </div>
              <span className="t13" style={{ flex: 'none' }}>
                {fmtMetric(m, value.value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// -------------------------------------------------------------- norms

function NormsDetail({ item, report }: { item: ListItem; report: Report }) {
  const text = anchoredText(report, item)
  if (!text) return null
  return (
    <div className="card">
      <div className="t13 secondary" style={{ marginBottom: 8 }}>
        原文
      </div>
      <div className="font-normal">{text}</div>
    </div>
  )
}

function RevisionDetail({ item, tex }: { item: ListItem; tex: boolean }) {
  const r = item.revision
  if (!r) return null
  return (
    <>
      <div className="card">
        <div className="t13 secondary" style={{ marginBottom: 8 }}>
          原文
        </div>
        <div
          className="font-normal"
          style={{
            background: 'var(--high-tint)',
            borderRadius: 4,
            padding: '2px 6px',
            wordBreak: 'break-word',
          }}
        >
          {r.old}
        </div>
      </div>
      <div className="card">
        <div className="t13 secondary" style={{ marginBottom: 8 }}>
          修订为
        </div>
        <div
          className="font-normal"
          style={{
            background: 'var(--ok-tint)',
            borderRadius: 4,
            padding: '2px 6px',
            wordBreak: 'break-word',
          }}
        >
          {r.new}
        </div>
      </div>
      <div className="t13 secondary">
        {tex
          ? '导出后写入 clover-revisions.patch，可以在编辑器里逐块审阅后应用。'
          : '导出后在 Word 中以修订形式出现，可以逐条接受或拒绝。'}
      </div>
    </>
  )
}

// ------------------------------------------- collapsed reorder group

/** first bracketed/dotted number in a revision's old/new text */
function leadNumber(s: string | undefined): string {
  const m = (s ?? '').match(/\d+/)
  return m ? m[0] : '—'
}

function ReorderDetail({
  item,
  report,
}: {
  item: ListItem
  report: Report
}) {
  const refs = (item.revisions ?? []).filter((r) => r.kind === 'ref_reorder')
  const titleOf = (anchorPara: string | undefined) => {
    const ref = (report.references ?? []).find(
      (r) => r.paragraph_id === anchorPara
    )
    return ref?.title ?? ''
  }
  return (
    <>
      <div className="card">
        <div className="t13 secondary" style={{ marginBottom: 8 }}>
          编号变化
        </div>
        <div className="flex flex-col" style={{ gap: 4 }}>
          {refs.map((r) => {
            const title = titleOf(r.anchor?.paragraph_id)
            return (
              <div key={r.id} className="flex items-baseline gap-2">
                <span
                  className="t13 secondary"
                  style={{ minWidth: 28, textAlign: 'right' }}
                >
                  {leadNumber(r.old)}
                </span>
                <span className="t13 secondary" aria-label="改为">→</span>
                <span
                  className="t13 font-semibold"
                  style={{ minWidth: 28 }}
                >
                  {leadNumber(r.new)}
                </span>
                <span className="t13 secondary clamp-2 min-w-0">{title}</span>
              </div>
            )
          })}
          {!refs.length && (
            <div className="t13 secondary">仅正文编号需要更新。</div>
          )}
        </div>
      </div>
    </>
  )
}
