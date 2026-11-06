/** Windows draws the minimise / maximise / close buttons on a solid
 *  overlay (titleBarOverlay). Keep that overlay the colour of whatever
 *  surface currently sits under the top-right corner: the inspector's
 *  --bg-subtle, or --bg once it is collapsed and on the other screens. */

/** First opaque background at (x, y), as #rrggbb; null if none. */
export function surfaceColorAt(x: number, y: number): string | null {
  let el = document.elementFromPoint(x, y) as Element | null
  while (el) {
    const hex = toHex(getComputedStyle(el).backgroundColor)
    if (hex) return hex
    el = el.parentElement
  }
  return null
}

/** A computed opaque colour → #rrggbb; transparent or translucent → null. */
export function toHex(css: string): string | null {
  const m = css.match(/^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/)
  if (!m) return null
  if (m[4] !== undefined) {
    const a = m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4])
    if (a < 1) return null
  }
  return '#' + [m[1], m[2], m[3]]
    .map((v) => Number(v).toString(16).padStart(2, '0'))
    .join('')
}

/** Follow layout, pane and theme changes; send only when the colour changes. */
export function trackCaptionColor(send: (hex: string) => void): void {
  let last = ''
  let queued = false
  const check = () => {
    queued = false
    // a few px inside the corner, under the caption buttons
    // screens with a transparent root show the window background, --bg
    const hex = surfaceColorAt(window.innerWidth - 8, 8) ??
      getComputedStyle(document.documentElement).getPropertyValue('--bg').trim().toLowerCase()
    if (/^#[0-9a-f]{6}$/.test(hex) && hex !== last) {
      last = hex
      send(hex)
    }
  }
  const schedule = () => {
    if (queued) return
    queued = true
    requestAnimationFrame(check)
  }
  new MutationObserver(schedule).observe(document.documentElement, {
    subtree: true, childList: true, attributes: true,
    attributeFilter: ['class', 'style', 'data-theme'],
  })
  window.addEventListener('resize', schedule)
  // pane collapse animates width; the final surface is known at the end
  document.addEventListener('transitionend', schedule)
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', schedule)
  schedule()
}
