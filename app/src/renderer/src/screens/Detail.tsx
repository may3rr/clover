import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Report, RefCheck, SectionDist } from '../types/report'
import type { ListItem } from '../lib/items'
import { supportForFinding } from '../lib/claims'
import { barGeom, comparedSections } from '../lib/dist'
import { ChevronLeftIcon } from '../components/Icons'

interface Props {
  item: ListItem
  report: Report
  backLabel: string
  onBack: () => void
}

const VERDICT: Record<string, { label: string; cls: string }> = {
  supported: { label: '支持', cls: 'sem-ok' },
  partial: { label: '部分支持', cls: 'sem-medium' },
  unsupported: { label: '不支持', cls: 'sem-high' },
  undetermined: { label: '无法判断', cls: 'secondary' },
}

export default function Detail({ item, report, backLabel, onBack }: Props) {
  return (
    <div className="detail-in flex flex-col flex-1 min-h-0" key={item.id}>
      <div
        className="drag-strip flex items-center"
        style={{ height: 52, flex: 'none', padding: '0 16px' }}
      >
        <button
          className="link-accent flex items-center gap-1"
          onClick={onBack}
        >
          <ChevronLeftIcon size={15} />
          {backLabel}
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        <div style={{ padding: '0 16px 16px' }}>
          <div className="font-semibold detail-title" style={{ fontSize: 17 }}>
            {item.title}
          </div>
          <div
            className="flex flex-col"
            style={{ gap: 12, marginTop: 16 }}
          >
            {item.kind === 'group' ? (
              <ReorderDetail item={item} report={report} />
            ) : item.kind === 'revision' ? (
              <RevisionDetail item={item} />
            ) : (
              <FindingDetail item={item} report={report} />
            )}
            <DetailLines detail={item.detail} />
          </div>
        </div>
      </div>
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

function FindingDetail({ item, report }: { item: ListItem; report: Report }) {
  if (item.layer === 'support')
    return <SupportDetail item={item} report={report} />
  if (item.layer === 'authenticity')
    return <AuthenticityDetail item={item} report={report} />
  if (item.layer === 'distribution')
    return <DistributionDetail item={item} report={report} />
  return <NormsDetail item={item} report={report} />
}

function SupportDetail({ item, report }: { item: ListItem; report: Report }) {
  const s = supportForFinding(report, item)
  const verdict = VERDICT[s.label ?? 'undetermined']
  return (
    <>
      {s.sentence && (
        <div className="card">
          <div className="t13 secondary" style={{ marginBottom: 8 }}>
            你的论文写道
          </div>
          <div className="font-normal">
            {s.claim && s.claim.start != null && s.claim.end != null ? (
              <>
                {s.sentence.slice(0, s.claim.start)}
                <span className="font-semibold">
                  {s.sentence.slice(s.claim.start, s.claim.end)}
                </span>
                {s.sentence.slice(s.claim.end)}
              </>
            ) : (
              s.sentence
            )}
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
            {s.sourceKind === 'fulltext' ? '依据开放全文' : '依据摘要'}
          </div>
        </div>
      )}
      <div>
        <span className={`font-semibold ${verdict.cls}`}>{verdict.label}</span>
        {s.rationale && (
          <span className="font-normal" style={{ marginLeft: 8 }}>
            {s.rationale}
          </span>
        )}
      </div>
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
  const theirs = (k: string): string | null => {
    if (!matched) return null
    const v = matched[k]
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

  const srcName = matched?.source ? String(matched.source) : ''
  const doiUrl = matched?.doi
    ? `https://doi.org/${String(matched.doi).replace(/^https?:\/\/doi.org\//, '')}`
    : ref?.doi
      ? `https://doi.org/${ref.doi.replace(/^https?:\/\/doi.org\//, '')}`
      : null

  return (
    <>
      <div className="flex gap-2">
        <div className="card flex-1 min-w-0" style={{ padding: 12 }}>
          <div className="t13 secondary" style={{ marginBottom: 8 }}>
            你写的
          </div>
          {rows.map(([label, yours, _t, bad]) => (
            <FieldRow key={label} label={label} value={yours} bad={bad} />
          ))}
        </div>
        <div className="card flex-1 min-w-0" style={{ padding: 12 }}>
          <div className="t13 secondary" style={{ marginBottom: 8 }}>
            {check?.status === 'not_found' || !matched
              ? '数据库中查到的'
              : `数据库中查到的（${srcName}）`}
          </div>
          {check?.status === 'not_found' ? (
            <div className="font-normal">三个数据库均未找到这篇文献</div>
          ) : matched ? (
            rows.map(([label, _y, t, bad]) => (
              <FieldRow key={label} label={label} value={t ?? '—'} bad={bad} />
            ))
          ) : (
            <div className="font-normal">暂无法完成核验</div>
          )}
        </div>
      </div>
      {doiUrl && (
        <button
          className="link-accent font-normal"
          onClick={() => window.citecheck.openExternal(doiUrl)}
        >
          {doiUrl}
        </button>
      )}
    </>
  )
}

function FieldRow({
  label,
  value,
  bad,
}: {
  label: string
  value: string
  bad: boolean
}) {
  return (
    <div style={{ marginBottom: 4 }}>
      <div className="t13 secondary">{label}</div>
      <div
        className="font-normal"
        style={{
          fontSize: 13,
          background: bad ? 'var(--high-tint)' : 'transparent',
          borderRadius: 4,
          padding: '1px 4px',
          wordBreak: 'break-word',
        }}
      >
        {value || '—'}
      </div>
    </div>
  )
}

// -------------------------------------------------------- distribution

function DistributionDetail({
  item,
  report,
}: {
  item: ListItem
  report: Report
}) {
  const d = report.distribution
  const secs = d ? comparedSections(d) : []
  const only = item.anchors[0]?.paragraph_id
  const shown = only
    ? secs.filter((s) => {
        const sec = (report.sections ?? []).find((x) => x.id === s.section_id)
        return sec?.heading_paragraph_id === only
      })
    : secs
  const rows = shown.length ? shown : secs
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

function RevisionDetail({ item }: { item: ListItem }) {
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
        {r.reason && (
          <div className="t13 secondary" style={{ marginTop: 8 }}>
            {r.reason}
          </div>
        )}
      </div>
      <div className="t13 secondary">
        导出后在 Word 中以修订形式出现，可以逐条接受或拒绝。
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
      <div className="t13 secondary">
        导出后在 Word 中以修订形式出现，可以逐条接受或拒绝。
      </div>
    </>
  )
}
