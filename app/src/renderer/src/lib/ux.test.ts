import { describe, it, expect } from 'vitest'
import { mathPieces } from './math'
import { formatLoc, isPaperPath, looksLikeFolder } from './accept'
import { layerFrac, overallProgress } from './progress'
import { assetUrl, layoutBlocks } from './layout'

const text = 'Let o_t ∈ O and x^2 hold.'
const math = [
  {
    start: 4,
    end: 11,
    runs: [
      ['o', ''],
      ['t', 'sub'],
      [' ∈ O', ''],
    ] as [string, '' | 'sub' | 'sup'][],
  },
  {
    start: 16,
    end: 19,
    runs: [
      ['x', ''],
      ['2', 'sup'],
    ] as [string, '' | 'sub' | 'sup'][],
  },
]

describe('mathPieces', () => {
  it('replaces whole formulas inside the range', () => {
    const p = mathPieces(text, 0, text.length, math)
    expect(p.map((x) => x.kind)).toEqual([
      'text',
      'math',
      'text',
      'math',
      'text',
    ])
    expect(p.map((x) => x.text).join('')).toBe(text)
  })
  it('leaves a formula cut by the range boundary as plain text', () => {
    const p = mathPieces(text, 0, 8, math)
    expect(p).toEqual([{ kind: 'text', text: 'Let o_t ' }])
  })
  it('handles paragraphs without math', () => {
    expect(mathPieces('plain', 0, 5, undefined)).toEqual([
      { kind: 'text', text: 'plain' },
    ])
  })
})

describe('accept helpers', () => {
  it('accepts docx and LaTeX archives', () => {
    expect(isPaperPath('/a/paper.docx')).toBe(true)
    expect(isPaperPath('/a/2106.09685.tar.gz')).toBe(true)
    expect(isPaperPath('/a/proj.zip')).toBe(true)
    expect(isPaperPath('/a/notes.pdf')).toBe(false)
    expect(looksLikeFolder('/Users/me/overleaf-project/')).toBe(true)
  })
  it('formats source locations', () => {
    expect(formatLoc('sections/intro.tex:42')).toBe(
      'sections/intro.tex 第 42 行'
    )
    expect(formatLoc(null)).toBe(null)
  })
})

describe('running progress', () => {
  it('weights layers and caps below 100% until finished', () => {
    const layers = {
      authenticity: { status: 'done' as const },
      support: { status: 'running' as const, frac: 0.5 },
      norms: { status: 'done' as const },
      distribution: { status: 'done' as const },
    }
    const p = overallProgress(layers, false)
    expect(p).toBeCloseTo((0.3 + 0.175 + 0.15 + 0.1) / 0.9, 5)
    expect(overallProgress({ a: { status: 'done' } }, false)).toBe(0.99)
    expect(overallProgress(layers, true)).toBe(1)
  })
  it('treats failed layers as finished and waiting as zero', () => {
    expect(layerFrac({ status: 'failed' })).toBe(1)
    expect(layerFrac({ status: 'waiting', frac: 0.8 })).toBe(0)
    expect(layerFrac({ status: 'running', frac: 3 })).toBe(1)
  })
})

describe('layoutBlocks', () => {
  const para = (id: string, text: string, cell?: object) =>
    ({ id, section_id: 's0', text, char_offset: 0, cell }) as never
  it('groups a table run and fills column gaps', () => {
    const blocks = layoutBlocks([
      para('p0', 'Intro.'),
      para('p1', 'BLEU', { table: 't0', row: 0, col: 1, colspan: 2, header: true }),
      para('p2', 'Base', { table: 't0', row: 1, col: 0 }),
      para('p3', '41.0', { table: 't0', row: 1, col: 2 }),
      para('p4', '', { table: 't0', row: 2, col: 0 }),
      para('p5', 'After.'),
    ])
    expect(blocks.map((b) => b.kind)).toEqual(['para', 'table', 'para'])
    const t = blocks[1]
    if (t.kind !== 'table') throw new Error('expected table')
    expect(t.cols).toBe(3)
    expect(t.rows).toHaveLength(2) // the all-blank row is dropped
    expect(t.rows[0].map((c) => [c.col, c.colspan, c.header])).toEqual([
      [0, 1, true],
      [1, 2, true],
    ])
    expect(t.rows[1].map((c) => c.paras.map((p) => p.text))).toEqual([
      ['Base'],
      [],
      ['41.0'],
    ])
  })
  it('splits two adjacent tables', () => {
    const blocks = layoutBlocks([
      para('p0', 'a', { table: 't0', row: 0, col: 0 }),
      para('p1', 'b', { table: 't1', row: 0, col: 0 }),
    ])
    expect(blocks).toHaveLength(2)
  })
  it('builds asset urls with the token', () => {
    expect(assetUrl('http://127.0.0.1:8765', 'k', 'x1', 'a b.png')).toBe(
      'http://127.0.0.1:8765/assets/x1/a%20b.png?token=k'
    )
  })
})
