import { useCallback, useEffect, useRef, useState } from 'react'
import { matchRanges } from '../lib/search'
import { ChevronDownIcon, ChevronUpIcon, MagnifierIcon } from './Icons'

const ALL = 'cc-search'
const CUR = 'cc-search-cur'

function reducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** ⌘F in the reading pane: matches are painted with the CSS Custom
 *  Highlight API, so the issue marks and the DOM stay untouched. */
export default function PaperSearch({
  rootRef,
  focusTick,
  onClose,
}: {
  rootRef: React.RefObject<HTMLElement | null>
  /** bumps on every ⌘F so a second press reselects the query */
  focusTick: number
  onClose: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [ranges, setRanges] = useState<Range[]>([])
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    input.current?.focus()
    input.current?.select()
  }, [focusTick])

  // recompute on query change and whenever the paper re-renders (a new
  // selection re-splits the highlight spans, invalidating old ranges)
  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    let frame = 0
    const run = () => {
      frame = 0
      setRanges(query.trim() ? matchRanges(root, query) : [])
    }
    run()
    const mo = new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(run)
    })
    mo.observe(root, { childList: true, subtree: true, characterData: true })
    return () => {
      mo.disconnect()
      if (frame) cancelAnimationFrame(frame)
    }
  }, [query, rootRef])

  const cur = ranges.length ? Math.min(idx, ranges.length - 1) : -1

  useEffect(() => {
    const reg = CSS.highlights
    if (!reg) return
    reg.set(ALL, new Highlight(...ranges.filter((_, i) => i !== cur)))
    if (cur >= 0) reg.set(CUR, new Highlight(ranges[cur]))
    else reg.delete(CUR)
  }, [ranges, cur])

  useEffect(
    () => () => {
      CSS.highlights?.delete(ALL)
      CSS.highlights?.delete(CUR)
    },
    []
  )

  const reveal = useCallback(
    (r: Range | undefined) => {
      const root = rootRef.current
      if (!root || !r) return
      const box = r.getBoundingClientRect()
      const view = root.getBoundingClientRect()
      if (box.top >= view.top + 48 && box.bottom <= view.bottom - 48) return
      root.scrollTo({
        top: root.scrollTop + box.top - view.top - root.clientHeight / 2,
        behavior: reducedMotion() ? 'auto' : 'smooth',
      })
    },
    [rootRef]
  )

  // typing jumps to the first match
  useEffect(() => {
    setIdx(0)
  }, [query])
  const firstReveal = useRef('')
  useEffect(() => {
    if (ranges.length && firstReveal.current !== query) {
      firstReveal.current = query
      reveal(ranges[0])
    }
  }, [ranges, query, reveal])

  const go = (delta: number) => {
    if (!ranges.length) return
    const next = (cur + delta + ranges.length) % ranges.length
    setIdx(next)
    reveal(ranges[next])
  }

  const count = !query.trim()
    ? ''
    : ranges.length
      ? `${cur + 1}/${ranges.length}`
      : '无结果'

  return (
    <div className="paper-search">
      <span className="secondary" style={{ flex: 'none' }}>
        <MagnifierIcon size={15} />
      </span>
      <input
        ref={input}
        className="paper-search-input"
        value={query}
        placeholder="在正文中查找"
        spellCheck={false}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            go(e.shiftKey ? -1 : 1)
          } else if (e.key === 'Escape') {
            e.preventDefault()
            onClose()
          }
        }}
      />
      <span className="t13 secondary" style={{ flex: 'none' }}>
        {count}
      </span>
      <button
        className="icon-btn"
        aria-label="上一个"
        disabled={!ranges.length}
        onClick={() => go(-1)}
      >
        <ChevronUpIcon size={16} />
      </button>
      <button
        className="icon-btn"
        aria-label="下一个"
        disabled={!ranges.length}
        onClick={() => go(1)}
      >
        <ChevronDownIcon size={16} />
      </button>
      <button className="pill-quiet t13" onClick={onClose}>
        完成
      </button>
    </div>
  )
}
