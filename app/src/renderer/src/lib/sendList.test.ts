import { describe, expect, it } from 'vitest'
import {
  categoryLine,
  itemMeta,
  manuscriptLine,
  sendHeadline,
  skippedLine,
} from './sendList'
import type { SendSummary } from '../types/report'

const base: SendSummary = {
  manuscript_chars: 12345,
  requests: 20,
  sent_chars: 3210,
  manuscript_sent_chars: 800,
  categories: [
    { category: 'claim', label: '论断', count: 12, chars: 800 },
    { category: 'excerpt', label: '被引片段', count: 40, chars: 2000 },
    { category: 'reference', label: '参考文献', count: 30, chars: 300 },
  ],
  skipped: [],
}

describe('send list wording', () => {
  it('states the manuscript size and what was sent', () => {
    expect(sendHeadline(base)).toBe('正文 12,345 字，发往云端 3,210 字')
    expect(sendHeadline({ ...base, requests: 0 })).toBe('正文 12,345 字，没有向云端发送内容')
  })

  it('lists categories with their units in backend order', () => {
    expect(categoryLine(base)).toBe('论断 12 句，被引片段 40 段，参考文献 30 条')
    expect(categoryLine({ ...base, categories: [] })).toBe('')
  })

  it('says how much of the manuscript itself left', () => {
    expect(manuscriptLine(base)).toBe('其中出自稿件的文字 800 字，包括带引用的论断句。')
    const more = {
      ...base,
      categories: [
        ...(base.categories ?? []),
        { category: 'manuscript' as const, label: '稿件正文', count: 3, chars: 90 },
      ],
    }
    expect(manuscriptLine(more)).toContain('和其他正文段落')
    expect(manuscriptLine({ ...base, manuscript_sent_chars: 0 })).toBe('稿件里的文字没有发往云端。')
    expect(manuscriptLine({ ...base, requests: 0 })).toBeNull()
  })

  it('names skipped tasks once and the next step', () => {
    expect(skippedLine(base)).toBeNull()
    const s = skippedLine({
      ...base,
      skipped: [
        { task: 'typo', label: '错别字检查', count: 9 },
        { task: 'review', label: '支持度复核', count: 1 },
        { task: 'review_fallback', label: '支持度复核', count: 1 },
      ],
    })
    expect(s).toBe(
      '隐私模式跳过了错别字检查、支持度复核，因为本机没有可用的模型。配置本机模型后重新体检，可以补上这些检查。'
    )
  })

  it('describes one item', () => {
    expect(itemMeta(1, ['支持度判断'])).toBe('支持度判断')
    expect(itemMeta(3, ['支持度判断', '重排'])).toBe('支持度判断、重排，发送 3 次')
  })
})
