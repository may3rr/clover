/** Case-insensitive occurrences of `needle` in `hay` as [start, end). */
export function findMatches(hay: string, needle: string): [number, number][] {
  const q = needle.trim().toLocaleLowerCase()
  if (!q) return []
  const h = hay.toLocaleLowerCase()
  const out: [number, number][] = []
  let i = h.indexOf(q)
  while (i !== -1) {
    out.push([i, i + q.length])
    i = h.indexOf(q, i + q.length)
  }
  return out
}

/** Text ranges of every match under `root` (matches may span the nodes a
 *  highlight or a math run splits the text into). */
export function matchRanges(root: HTMLElement, needle: string): Range[] {
  const nodes: Text[] = []
  const starts: number[] = []
  let hay = ''
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const t = n as Text
    if (!t.data) continue
    nodes.push(t)
    starts.push(hay.length)
    hay += t.data
  }
  const at = (pos: number, end: boolean): [Text, number] => {
    // last node starting at or before pos (for an end, strictly before)
    let lo = 0
    let hi = nodes.length - 1
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1
      if (end ? starts[mid] < pos : starts[mid] <= pos) lo = mid
      else hi = mid - 1
    }
    return [nodes[lo], pos - starts[lo]]
  }
  return findMatches(hay, needle).map(([a, b]) => {
    const r = document.createRange()
    const [sn, so] = at(a, false)
    const [en, eo] = at(b, true)
    r.setStart(sn, so)
    r.setEnd(en, eo)
    return r
  })
}
