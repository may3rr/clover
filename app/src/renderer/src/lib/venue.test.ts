import { describe, expect, it } from 'vitest'
import { boolSummary, exemplarRows, fmtMetric, groupedMetrics, metricsFor } from './venue'
import type { Distribution, VenueMetric } from '../types/report'

const m = (over: Partial<VenueMetric>): VenueMetric => ({
  key: 'n_refs',
  group: 'references',
  label: '参考文献数量',
  unit: '条',
  kind: 'number',
  exemplars: [],
  ...over,
})

const dist = {
  benchmark_id: 'venue:x',
  benchmark_name: '《x》范文',
  n_papers: 3,
  comparable_density: true,
  venue_metrics: [
    m({ key: 'n_refs' }),
    m({ key: 'func:method', group: 'functions', unit: '%', kind: 'share' }),
    m({ key: 'present:intro', group: 'structure', kind: 'bool', unit: '' }),
  ],
} as Distribution

describe('venue measures', () => {
  it('formats values by unit and kind', () => {
    expect(fmtMetric({ unit: '%', kind: 'share' }, 0.437)).toBe('44%')
    expect(fmtMetric({ unit: '条', kind: 'number' }, 51)).toBe('51 条')
    expect(fmtMetric({ unit: '年', kind: 'number' }, 2)).toBe('2.0 年')
    expect(fmtMetric({ unit: '', kind: 'bool' }, 0)).toBe('没有')
    expect(fmtMetric({ unit: '条', kind: 'number' }, null)).toBe('未知')
  })

  it('finds a finding’s measures and groups the rest', () => {
    expect(metricsFor(dist, ['func:method', 'missing', 'n_refs']).map((x) => x.key)).toEqual([
      'func:method',
      'n_refs',
    ])
    expect(groupedMetrics(dist).map(([g]) => g)).toEqual(['structure', 'references', 'functions'])
  })

  it('lists the topic-closest exemplars first, then by value', () => {
    const metric = m({
      exemplars: [
        { doc_id: 'a', value: 30 },
        { doc_id: 'b', value: 50, page: 9 },
        { doc_id: 'c', value: 40 },
        { doc_id: 'd', value: null },
      ],
    })
    const infos = ['a', 'b', 'c', 'd'].map((id) => ({
      doc_id: id,
      filename: `${id}.pdf`,
      similar: id === 'a',
    }))
    expect(exemplarRows(metric, infos).map((r) => r.value.doc_id)).toEqual(['a', 'b', 'c', 'd'])
  })

  it('summarises a yes/no measure', () => {
    expect(boolSummary(m({ kind: 'bool', value: 0, rate: 0.68 }))).toBe('本文没有，范文中 68% 有')
    expect(boolSummary(m({ kind: 'bool', value: null }))).toBe('本文无法判断')
  })
})
