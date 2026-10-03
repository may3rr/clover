/** "导出到 Word" illustration, built from the showcase report itself: one
 *  paragraph of the paper with its typo revision drawn as a tracked change
 *  and its findings as comment balloons, worded exactly as the exporter
 *  writes them (title line, then the detail lines). */
import type { Report } from '../../../src/renderer/src/types/report'

const PARA = 'p20'
const AUTHOR = '李明'

type Span = { start: number; end: number; kind: 'rev' | 'comment'; n?: number; old?: string; new?: string }

const esc = (s: string) =>
  s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!)

export async function renderDoc(fig: HTMLElement) {
  const r: Report = await fetch('./data/showcase.json').then((x) => x.json())
  const para = (r.paragraphs ?? []).find((p) => p.id === PARA)
  if (!para) return
  const section = (r.sections ?? []).find((s) => s.id === para.section_id)
  const text = para.text ?? ''

  const spans: Span[] = []
  for (const v of r.revisions ?? [])
    if (v.anchor?.paragraph_id === PARA)
      spans.push({ start: v.anchor.start!, end: v.anchor.end!, kind: 'rev', old: v.old!, new: v.new! })
  const comments = (r.findings ?? []).filter((f) => f.anchor?.paragraph_id === PARA)
  comments.forEach((f, i) =>
    spans.push({ start: f.anchor!.start!, end: f.anchor!.end!, kind: 'comment', n: i })
  )
  spans.sort((a, b) => a.start - b.start)

  let html = ''
  let at = 0
  for (const s of spans) {
    if (s.start < at) continue
    html += esc(text.slice(at, s.start))
    if (s.kind === 'rev') html += `<del>${esc(s.old!)}</del><ins>${esc(s.new!)}</ins>`
    else html += `<mark data-n="${s.n}">${esc(text.slice(s.start, s.end))}</mark>`
    at = s.end
  }
  html += esc(text.slice(at))

  const initials = 'LM'
  const balloon = (title: string, lines: string[], kind: string, n?: number) => `
    <div class="balloon"${n === undefined ? '' : ` data-n="${n}"`}>
      <div class="balloon-who"><i>${initials}</i>${AUTHOR}<span class="balloon-kind">${kind}</span></div>
      <p class="t">${esc(title)}</p>
      ${lines.map((l) => `<p>${esc(l)}</p>`).join('')}
    </div>`

  const rev = spans.find((s) => s.kind === 'rev')
  fig.innerHTML = `
    <div class="doc-page">
      ${section?.title ? `<p class="doc-h">${esc(section.title)}</p>` : ''}
      <p>${html}</p>
    </div>
    <div class="balloons">
      ${rev ? balloon(`删除 ${rev.old}，插入 ${rev.new}`, [], '修订') : ''}
      ${comments
        .map((f, i) =>
          balloon(
            f.title ?? '',
            (f.detail ?? '').split('\n').filter((l) => l.trim()),
            '批注',
            i
          )
        )
        .join('')}
    </div>`

  // hovering a balloon lights its range, and the other way round
  const light = (n: string | undefined, on: boolean) =>
    fig.querySelectorAll(`mark[data-n="${n}"]`).forEach((m) => m.classList.toggle('on', on))
  for (const el of fig.querySelectorAll<HTMLElement>('[data-n]')) {
    el.addEventListener('mouseenter', () => light(el.dataset.n, true))
    el.addEventListener('mouseleave', () => light(el.dataset.n, false))
  }
}
