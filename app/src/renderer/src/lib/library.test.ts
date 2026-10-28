import { describe, expect, it } from 'vitest'
import {
  baselineText,
  counts,
  docLabel,
  exemplarCandidates,
  exemplarMeta,
  finalLinks,
  initialChoice,
  pickedExemplars,
  rowState,
  venueState,
  type LibraryScan,
} from './library'

const doc = (id: string, venue: string | null, extra = {}) => ({
  id,
  filename: `${id}.pdf`,
  venue,
  title: `标题${id}`,
  authors: ['张三'],
  year: 2026,
  ...extra,
})

const scan: LibraryScan = {
  paper: '/p/paper.docx',
  candidates: [],
  kind: 'docx',
  baseline: { source: null, name: '数据分析与知识发现', n_papers: 3 },
  references: ['r1', 'r2', 'r3'].map((id) => ({
    id,
    label: id.slice(1),
    title: id,
    authors: [],
    year: null,
    lang: 'zh',
    raw: id,
  })),
  library: {
    folder: '/p/ref',
    venue: '数据分析与知识发现',
    docs: [
      doc('a', '数据分析与知识发现'),
      doc('b', '数据分析与知识发现'),
      doc('c', '数据分析与知识发现'),
      doc('s', null, { readable: false }),
    ],
    links: [
      { ref_id: 'r1', doc_id: 'a', method: 'title', score: 100, status: 'auto' },
      { ref_id: 'r2', doc_id: 'b', method: 'llm', score: 80, status: 'review' },
    ],
    exemplar_ids: ['c'],
    venue_match_ids: ['c'],
    venue_source: 'folder',
  },
}

describe('link confirmation', () => {
  it('counts linked, review and none', () => {
    const ch = initialChoice(scan.library)
    expect(counts(scan, ch, new Set())).toEqual({ linked: 1, review: 1, none: 1 })
    expect(rowState(scan, ch, new Set(), 'r2')).toBe('review')
    // touching a model pick confirms it
    expect(counts(scan, ch, new Set(['r2']))).toEqual({ linked: 2, review: 0, none: 1 })
  })

  it('exemplar candidates follow edits; matches first, scans never', () => {
    const vs = venueState(scan)
    expect(exemplarCandidates(vs, { r1: 'a', r2: '', r3: '' }).map((d) => d.id)).toEqual(['c', 'b'])
    expect(exemplarCandidates(vs, { r1: 'a', r2: 'b', r3: 'c' })).toEqual([])
    // a picked PDF that gets linked drops out of the selection
    expect(pickedExemplars(new Set(['b', 'c']), vs, { r1: 'a', r2: '', r3: 'c' })).toEqual(['b'])
  })

  it('says which baseline the run will use', () => {
    const vs = venueState(scan)
    expect(baselineText(vs, 5)).toBe(
      '用文件夹中 5 篇《数据分析与知识发现》论文作为对标范文，逐篇统计后和本文比较。'
    )
    expect(baselineText({ ...vs, entry: { id: 'dakd', name: '数据分析与知识发现', n_papers: 36 } }, 2))
      .toContain('内置基线')
    expect(baselineText({ ...vs, venue: null }, 0)).toContain('填写目标期刊')
  })

  it('describes an exemplar without middle dots', () => {
    expect(
      exemplarMeta({ ...doc('a', '数据分析与知识发现'), venue_via: 'cnki_cover', paper_type: 'review' })
    ).toBe('《数据分析与知识发现》，2026，知网封面刊名，综述')
    expect(exemplarMeta(doc('b', null))).toBe('刊名未知，2026')
  })

  it('final links keep automatic ones and mark edits as user', () => {
    const links = finalLinks(scan, { r1: 'a', r2: '', r3: 'c' })
    expect(links).toEqual([
      { ref_id: 'r1', doc_id: 'a', method: 'title', score: 100, status: 'confirmed' },
      { ref_id: 'r3', doc_id: 'c', method: 'user', score: 100, status: 'confirmed' },
    ])
  })

  it('labels a PDF without middle dots', () => {
    expect(docLabel(doc('a', null))).toBe('标题a，张三，2026')
  })
})
