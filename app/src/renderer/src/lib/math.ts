import type { MathSpan } from '../types/report'

export type MathRun = [string, '' | 'sub' | 'sup']

export type Piece =
  | { kind: 'text'; text: string }
  | { kind: 'math'; text: string; runs: MathRun[] }

/** Split paragraph text [start, end) into plain text and LaTeX inline-math
 *  pieces. A math span is shown with its sub/superscripts only when it
 *  lies wholly inside the range; a highlight boundary cutting through a
 *  formula leaves both halves as their flattened text. */
export function mathPieces(
  text: string,
  start: number,
  end: number,
  math: MathSpan[] | undefined
): Piece[] {
  const inside = (math ?? [])
    .filter((m) => m.start >= start && m.end <= end && m.end > m.start)
    .sort((a, b) => a.start - b.start)
  const out: Piece[] = []
  let cur = start
  for (const m of inside) {
    if (m.start < cur) continue
    if (m.start > cur) out.push({ kind: 'text', text: text.slice(cur, m.start) })
    out.push({
      kind: 'math',
      text: text.slice(m.start, m.end),
      runs: (m.runs ?? []) as MathRun[],
    })
    cur = m.end
  }
  if (cur < end) out.push({ kind: 'text', text: text.slice(cur, end) })
  return out
}
