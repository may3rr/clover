import { describe, it, expect } from 'vitest'
import { segmentsForParagraph } from './highlight'
import { buildItems, moveSelection, pickItem, type ListItem } from './items'
import { supportForFinding } from './claims'
import { barGeom, comparedSections } from './dist'
import type { Finding, Report, Revision } from '../types/report'

function item(
  id: string,
  paragraphId: string | null,
  start: number,
  end: number,
  severity: ListItem['severity']
): ListItem {
  return {
    id,
    kind: 'finding',
    layer: 'norms',
    severity,
    title: id,
    detail: '',
    anchors: paragraphId
      ? [{ paragraph_id: paragraphId, start, end }]
      : [],
    paragraphId,
    start,
    finding: {
      id,
      layer: 'norms',
      severity: severity === 'rev' ? 'low' : severity,
      anchor: paragraphId
        ? { paragraph_id: paragraphId, start, end }
        : null,
      title: id,
      detail: '',
    } as Finding,
  }
}

describe('segmentsForParagraph', () => {
  const text = 'abcdefghij' // len 10

  it('returns one plain segment with no items', () => {
    expect(segmentsForParagraph(text, 'p1', [])).toEqual([
      { start: 0, end: 10, text, severity: null, selected: false, itemIds: [] },
    ])
  })

  it('splits at anchor bounds', () => {
    const segs = segmentsForParagraph(text, 'p1', [
      item('f1', 'p1', 2, 5, 'medium'),
    ])
    expect(segs.map((s) => [s.start, s.end, s.severity])).toEqual([
      [0, 2, null],
      [2, 5, 'medium'],
      [5, 10, null],
    ])
  })

  it('ignores anchors on other paragraphs', () => {
    const segs = segmentsForParagraph(text, 'p1', [
      item('f1', 'p2', 2, 5, 'high'),
    ])
    expect(segs).toHaveLength(1)
    expect(segs[0].severity).toBeNull()
  })

  it('overlap takes the highest severity and keeps both ids', () => {
    const segs = segmentsForParagraph(text, 'p1', [
      item('f1', 'p1', 0, 6, 'low'),
      item('f2', 'p1', 3, 8, 'high'),
    ])
    const mid = segs.find((s) => s.start === 3 && s.end === 6)
    expect(mid?.severity).toBe('high')
    expect(mid?.itemIds.sort()).toEqual(['f1', 'f2'])
    const tail = segs.find((s) => s.start === 6 && s.end === 8)
    expect(tail?.severity).toBe('high')
    const head = segs.find((s) => s.start === 0 && s.end === 3)
    expect(head?.severity).toBe('low')
  })

  it('marks segments covering the selected item', () => {
    const segs = segmentsForParagraph(
      text,
      'p1',
      [item('f1', 'p1', 0, 6, 'low'), item('f2', 'p1', 3, 8, 'high')],
      'f1'
    )
    expect(segs.find((s) => s.start === 0)?.selected).toBe(true)
    expect(segs.find((s) => s.start === 6)?.selected).toBe(false)
  })

  it('zero-length anchor expands to the whole paragraph', () => {
    const segs = segmentsForParagraph(text, 'p1', [
      item('f1', 'p1', 4, 4, 'low'),
    ])
    expect(segs).toHaveLength(1)
    expect(segs[0].severity).toBe('low')
    expect(segs[0].end).toBe(10)
  })

  it('clamps out-of-range anchors', () => {
    const segs = segmentsForParagraph(text, 'p1', [
      item('f1', 'p1', 8, 99, 'medium'),
    ])
    expect(segs[1].end).toBe(10)
  })
})

describe('buildItems ordering', () => {
  const report = {
    paragraphs: [
      { id: 'p1', text: 'a' },
      { id: 'p2', text: 'b' },
      { id: 'p3', text: 'c' },
    ],
    findings: [
      { id: 'f2', layer: 'norms', severity: 'low', anchor: { paragraph_id: 'p3', start: 0, end: 1 }, title: '', detail: '' },
      { id: 'f1', layer: 'norms', severity: 'low', anchor: { paragraph_id: 'p2', start: 0, end: 1 }, title: '', detail: '' },
      { id: 'f0', layer: 'norms', severity: 'low', anchor: null, title: '', detail: '' },
    ],
    revisions: [
      { id: 'v1', kind: 'typo', anchor: { paragraph_id: 'p2', start: 3, end: 4 }, old: 'x', new: 'y', reason: '' },
    ],
  } as unknown as Report

  it('anchor-less first, then paragraph order', () => {
    const items = buildItems(report)
    expect(items.map((i) => i.id)).toEqual(['f0', 'f1', 'v1', 'f2'])
  })

  it('revision rows are titled 建议修订', () => {
    const items = buildItems(report)
    expect(items.find((i) => i.id === 'v1')?.title).toBe('建议修订：x 改为 y')
    expect(items.find((i) => i.id === 'v1')?.layer).toBe('norms')
  })
})

describe('buildItems reorder collapse', () => {
  const report = {
    paragraphs: [
      { id: 'p1', text: 'a' },
      { id: 'p9', text: 'refs' },
    ],
    findings: [],
    revisions: [
      { id: 'm1', kind: 'marker_renumber', anchor: { paragraph_id: 'p1', start: 0, end: 3 }, old: '[2]', new: '[1]', reason: '' },
      { id: 'm2', kind: 'marker_renumber', anchor: { paragraph_id: 'p1', start: 5, end: 8 }, old: '[4]', new: '[2]', reason: '' },
      { id: 'r1', kind: 'ref_reorder', anchor: { paragraph_id: 'p9', start: 0, end: 2 }, old: '2.', new: '1.', reason: '', move_after: '__start__' },
      { id: 'v1', kind: 'typo', anchor: { paragraph_id: 'p1', start: 10, end: 11 }, old: 'x', new: 'y', reason: '' },
    ],
  } as unknown as Report

  it('collapses marker_renumber + ref_reorder into one norms item', () => {
    const items = buildItems(report)
    const group = items.find((i) => i.kind === 'group')
    expect(group).toBeTruthy()
    expect(group!.layer).toBe('norms')
    expect(group!.title).toBe('按首次引用顺序重排参考文献')
    expect(group!.detail).toContain('2 处正文编号')
    expect(group!.detail).toContain('1 条参考文献')
    expect(group!.anchors).toHaveLength(3)
    // typo revisions stay individual
    expect(items.filter((i) => i.kind === 'revision')).toHaveLength(1)
  })
})

describe('moveSelection', () => {
  const items = [
    { id: 'a' }, { id: 'b' }, { id: 'c' },
  ] as ListItem[]

  it('moves down and up, clamped at edges', () => {
    expect(moveSelection(items, 'a', 1)).toBe('b')
    expect(moveSelection(items, 'c', 1)).toBe('c')
    expect(moveSelection(items, 'a', -1)).toBe('a')
    expect(moveSelection(items, 'b', -1)).toBe('a')
  })

  it('starts at the ends when nothing is selected', () => {
    expect(moveSelection(items, null, 1)).toBe('a')
    expect(moveSelection(items, null, -1)).toBe('c')
  })

  it('returns null for empty lists', () => {
    expect(moveSelection([], 'a', 1)).toBeNull()
  })
})

describe('pickItem', () => {
  it('picks the most severe, then the shortest span', () => {
    const a = item('a', 'p', 0, 9, 'medium')
    const b = item('b', 'p', 0, 9, 'high')
    const c = item('c', 'p', 0, 4, 'high')
    expect(pickItem([a, b, c])?.id).toBe('c')
  })
})

describe('supportForFinding', () => {
  const report = {
    paragraphs: [{ id: 'p1', text: 'Deep nets learn fast [1].' }],
    markers: [{ id: 'm1', paragraph_id: 'p1', start: 22, end: 25, raw: '[1]', ref_ids: ['r1'] }],
    claims: [
      {
        id: 'c1',
        paragraph_id: 'p1',
        start: 0,
        end: 22,
        text: 'Deep nets learn fast',
        marker_ids: ['m1'],
        sentence: 'Deep nets learn fast [1].',
      },
    ],
    support_checks: [
      {
        claim_id: 'c1',
        ref_id: 'r1',
        label: 'partial',
        source_kind: 'abstract',
        rationale: 'mostly',
        source_title: 'A paper',
        source_excerpt: 'nets learn',
        evidence_span: [5, 10],
      },
    ],
    findings: [
      {
        id: 'f1',
        layer: 'support',
        severity: 'medium',
        anchor: { paragraph_id: 'p1', start: 0, end: 25 },
        title: '',
        detail: '',
        refs: ['r1'],
      },
    ],
  } as unknown as Report

  it('resolves claim + check through the marker chain', () => {
    const it = buildItems(report).find((i) => i.id === 'f1')!
    const s = supportForFinding(report, it)
    expect(s.claim?.id).toBe('c1')
    expect(s.check?.claim_id).toBe('c1')
    expect(s.sentence).toBe('Deep nets learn fast [1].')
    expect(s.sourceTitle).toBe('A paper')
    expect(s.excerpt).toBe('nets learn')
    expect(s.evidenceSpan).toEqual([5, 10])
    expect(s.label).toBe('partial')
  })

  it('returns empty for non-finding items', () => {
    const rev = {
      id: 'v1', kind: 'revision', layer: 'norms', severity: 'rev',
      title: '', detail: '', paragraphId: 'p1', start: 0,
      anchors: [{ paragraph_id: 'p1', start: 0, end: 1 }],
      revision: { id: 'v1', kind: 'typo', anchor: { paragraph_id: 'p1', start: 0, end: 1 }, old: 'a', new: 'b', reason: '' } as Revision,
    } as ListItem
    expect(supportForFinding(report, rev).claim).toBeNull()
  })
})

describe('barGeom', () => {
  it('scales value and band onto a shared axis', () => {
    const g = barGeom(0.5, { q1: 0.1, q3: 0.4, median: 0.2 })
    expect(g.valueFrac).toBeCloseTo(0.5 / (0.5 * 1.15))
    expect(g.q3).toBeCloseTo(0.4 / (0.5 * 1.15))
    expect(g.median).toBeCloseTo(0.2 / (0.5 * 1.15))
    expect(g.q1).toBeCloseTo(0.1 / (0.5 * 1.15))
  })

  it('never exceeds 1 even when the bench is larger', () => {
    const g = barGeom(0.9, { q1: 0.1, q3: 0.5, median: 0.3 })
    expect(g.valueFrac).toBeLessThanOrEqual(1)
    expect(g.q3).toBeLessThanOrEqual(1)
  })

  it('handles null bench without crashing', () => {
    const g = barGeom(0.2, null)
    expect(g.q1).toBe(0)
    expect(g.q3).toBe(0)
    expect(g.valueFrac).toBeCloseTo(1 / 1.15)
  })
})

describe('comparedSections', () => {
  it('keeps only compared sections that were flagged', () => {
    const d = {
      sections: [
        { section_id: 's1', canonical: 'intro', title: 'Intro', words: 0, citations: 0, share: 0, density: 0, bench_share: { median: 0, q1: 0, q3: 0 }, share_flag: 'below' },
        { section_id: 's2', canonical: 'related', title: 'Rel', words: 0, citations: 0, share: 0, density: 0, bench_share: { median: 0, q1: 0, q3: 0 }, share_flag: 'within' },
        { section_id: 's3', canonical: 'method', title: 'M', words: 0, citations: 0, share: 0, density: 0 },
      ],
    }
    const out = comparedSections(d as never)
    expect(out.map((s) => s.section_id)).toEqual(['s1'])
  })
})
