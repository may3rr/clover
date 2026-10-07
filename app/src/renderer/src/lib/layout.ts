import type { Paragraph } from '../types/report'

export interface GridCell {
  col: number
  colspan: number
  header: boolean
  paras: Paragraph[] // several Word paragraphs may share one cell
}

export type Block =
  | { kind: 'para'; p: Paragraph }
  | { kind: 'table'; id: string; rows: GridCell[][]; cols: number }

/** Reading-view blocks: runs of consecutive same-table cell paragraphs
 *  become one grid; every other paragraph stays a block of its own. Gaps
 *  (empty LaTeX cells are not emitted) are filled so columns line up. */
export function layoutBlocks(paragraphs: Paragraph[]): Block[] {
  const out: Block[] = []
  let i = 0
  while (i < paragraphs.length) {
    const p = paragraphs[i]
    const cell = p.cell
    if (!cell) {
      out.push({ kind: 'para', p })
      i++
      continue
    }
    const run: Paragraph[] = []
    while (i < paragraphs.length && paragraphs[i].cell?.table === cell.table) {
      run.push(paragraphs[i])
      i++
    }
    out.push(buildTable(cell.table, run))
  }
  return out
}

function buildTable(id: string, run: Paragraph[]): Block {
  const byRow = new Map<number, Map<number, GridCell>>()
  let cols = 0
  for (const p of run) {
    const c = p.cell!
    const span = Math.max(c.colspan ?? 1, 1)
    cols = Math.max(cols, c.col + span)
    const row = byRow.get(c.row) ?? new Map<number, GridCell>()
    byRow.set(c.row, row)
    const hit = row.get(c.col)
    if (hit) hit.paras.push(p)
    else
      row.set(c.col, {
        col: c.col,
        colspan: span,
        header: !!c.header,
        paras: [p],
      })
  }
  const rows: GridCell[][] = []
  for (const r of [...byRow.keys()].sort((a, b) => a - b)) {
    const cells = [...byRow.get(r)!.values()].sort((a, b) => a.col - b.col)
    const header = cells.some((c) => c.header)
    const filled: GridCell[] = []
    let at = 0
    for (const c of cells) {
      if (c.col < at) continue // overlapping span: keep the first
      for (; at < c.col; at++)
        filled.push({ col: at, colspan: 1, header, paras: [] })
      filled.push(c)
      at = c.col + c.colspan
    }
    for (; at < cols; at++)
      filled.push({ col: at, colspan: 1, header, paras: [] })
    // a Word table's empty paragraphs leave all-blank rows: drop them
    const blank = filled.every((c) =>
      c.paras.every((p) => !(p.text ?? '').trim() && !p.images?.length)
    )
    if (!blank) rows.push(filled)
  }
  return { kind: 'table', id, rows, cols }
}

/** URL of an extracted figure (img tags can't send the auth header). */
export function assetUrl(
  baseUrl: string,
  token: string,
  bundle: string,
  name: string
): string {
  const q = token ? `?token=${encodeURIComponent(token)}` : ''
  const path = `${encodeURIComponent(bundle)}/${encodeURIComponent(name)}`
  return `${baseUrl}/assets/${path}${q}`
}
