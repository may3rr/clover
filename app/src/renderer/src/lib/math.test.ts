import { describe, it, expect } from 'vitest'
import { mathPieces } from './math'
import { formatLoc, isPaperPath, looksLikeFolder } from './accept'

const text = 'Let o_t ∈ O and x^2 hold.'
const math = [
  { start: 4, end: 11, runs: [['o', ''], ['t', 'sub'], [' ∈ O', '']] as [string, '' | 'sub' | 'sup'][] },
  { start: 16, end: 19, runs: [['x', ''], ['2', 'sup']] as [string, '' | 'sub' | 'sup'][] },
]

describe('mathPieces', () => {
  it('replaces whole formulas inside the range', () => {
    const p = mathPieces(text, 0, text.length, math)
    expect(p.map((x) => x.kind)).toEqual(['text', 'math', 'text', 'math', 'text'])
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
    expect(formatLoc('sections/intro.tex:42')).toBe('sections/intro.tex 第 42 行')
    expect(formatLoc(null)).toBe(null)
  })
})
