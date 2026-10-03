import { useEffect, useLayoutEffect, useRef } from 'react'

/** "Think Different"-style title: every letter flickers through unrelated
 * typefaces, then the whole line settles at once into an old-style serif.
 * Only fonts that ship with macOS — no web or bundled font files. Letter
 * widths are locked to the final face first, so the line never jitters. */

export const SETTLE_FONT =
  "'Hoefler Text', 'Iowan Old Style', 'Palatino', Georgia, serif"

const FONTS = [
  "'Didot', serif",
  "'Baskerville', serif",
  "'Futura', sans-serif",
  "'Avenir Next', sans-serif",
  "'Gill Sans', sans-serif",
  "'Optima', sans-serif",
  "'American Typewriter', serif",
  "'Courier New', monospace",
  "'Menlo', monospace",
  "'Copperplate', serif",
  "'Marker Felt', fantasy",
  "'Chalkboard SE', cursive",
  "'Snell Roundhand', cursive",
  "'Noteworthy', cursive",
  "'Impact', sans-serif",
  "'Rockwell', serif",
  "'Big Caslon', serif",
  "'Trattatello', fantasy",
]

const HOLD_MS = 1100
const SWAP_MIN = 120
const SWAP_MAX = 230

export default function ShuffleTitle({
  text,
  play,
  onSettled,
  className,
}: {
  text: string
  /** start flickering; settles after HOLD_MS */
  play: boolean
  onSettled?: () => void
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const settledCb = useRef(onSettled)
  settledCb.current = onSettled

  // lock each letter's width to the settled face
  useLayoutEffect(() => {
    const spans = Array.from(ref.current?.children ?? []) as HTMLElement[]
    if (!spans.length) return
    const fs = parseFloat(getComputedStyle(spans[0]).fontSize) || 16
    for (const el of spans) {
      el.style.fontFamily = SETTLE_FONT
      el.style.width = 'auto'
      el.style.width = `${el.getBoundingClientRect().width / fs}em`
    }
  }, [text])

  useEffect(() => {
    if (!play) return
    const spans = Array.from(ref.current?.children ?? []) as HTMLElement[]
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || window.citecheck.shotsMode) {
      settledCb.current?.()
      return
    }
    const next = spans.map(() => 0)
    let t0 = 0
    let raf = 0
    const frame = (now: number) => {
      if (!t0) t0 = now
      if (now - t0 >= HOLD_MS) {
        for (const el of spans) el.style.fontFamily = SETTLE_FONT
        settledCb.current?.()
        return
      }
      spans.forEach((el, i) => {
        if (now < next[i]) return
        el.style.fontFamily = FONTS[(Math.random() * FONTS.length) | 0]
        next[i] = now + SWAP_MIN + Math.random() * (SWAP_MAX - SWAP_MIN)
      })
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [play])

  return (
    <div
      ref={ref}
      className={className}
      role="img"
      aria-label={text}
      style={{ whiteSpace: 'pre', opacity: play ? 1 : 0 }}
    >
      {[...text].map((c, i) => (
        <span key={i} className="shuffle-ch">
          {c === ' ' ? ' ' : c}
        </span>
      ))}
    </div>
  )
}
