import { useEffect, useLayoutEffect, useRef } from 'react'

/** "Think Different"-style title: every letter flickers through unrelated
 * typefaces on its own clock, then the letters land one by one, left to
 * right, in an old-style serif.
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
  "'Bodoni 72', serif",
  "'Zapfino', cursive",
  "'Papyrus', fantasy",
  "'Herculanum', fantasy",
  "'Skia', sans-serif",
  "'Chalkduster', fantasy",
  "'Phosphate', fantasy",
  "'Luminari', fantasy",
  "'Savoye LET', cursive",
  "'Andale Mono', monospace",
  "'Trebuchet MS', sans-serif",
  "'Verdana', sans-serif",
]

const SHUFFLE_MS = 1400 // every letter flickers on its own clock
const SETTLE_MS = 900 // then letters land left to right
const SWAP_MIN = 70
const SWAP_MAX = 150

export default function ShuffleTitle({
  text,
  play,
  onSettled,
  className,
}: {
  text: string
  /** start flickering; lands after SHUFFLE_MS + SETTLE_MS */
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
    // each letter's landing time: left to right, with a little jitter
    const landAt = spans.map(
      (_, i) =>
        SHUFFLE_MS +
        (i / Math.max(1, spans.length - 1)) * SETTLE_MS +
        (Math.random() - 0.5) * 120
    )
    const landed = spans.map(() => false)
    let t0 = 0
    let raf = 0
    const frame = (now: number) => {
      if (!t0) t0 = now
      const t = now - t0
      spans.forEach((el, i) => {
        if (landed[i]) return
        if (t >= landAt[i]) {
          el.style.fontFamily = SETTLE_FONT
          landed[i] = true
          return
        }
        if (now < next[i]) return
        let f = FONTS[(Math.random() * FONTS.length) | 0]
        if (f === el.style.fontFamily) f = FONTS[(Math.random() * FONTS.length) | 0]
        el.style.fontFamily = f
        next[i] = now + SWAP_MIN + Math.random() * (SWAP_MAX - SWAP_MIN)
      })
      if (landed.every(Boolean)) {
        settledCb.current?.()
        return
      }
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
