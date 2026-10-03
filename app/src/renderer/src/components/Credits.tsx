import { useEffect, useRef } from 'react'
import { CREDITS } from '../lib/credits'
import { Chiptune } from '../lib/chiptune'
import { APP_NAME } from '../lib/brand'

/** Credits easter egg: a window-filling, game-style staff roll. Every name
 * flies from the lower left toward the upper right along a 30° line over
 * a drifting pixel starfield, with an 8-bit loop playing.
 *
 * Pixel lettering without a font file: each line is drawn with the
 * system font onto a tiny canvas, thresholded to hard pixels, then the
 * whole low-res frame is scaled up with smoothing off. */

const PX = 3 // screen px per "pixel"
const ANGLE = (30 * Math.PI) / 180
const UX = Math.cos(ANGLE)
const UY = -Math.sin(ANGLE)
const NX = Math.sin(ANGLE) // lane offset, perpendicular to travel
const NY = Math.cos(ANGLE)
const SPEED = 42 // low-res px per second
const GAP = 14 // low-res px of clear space between cards along the path

type Tone = 'title' | 'group' | 'name' | 'role'

interface Line {
  text: string
  tone: Tone
  color?: string // css var for group headings
}

const GROUP_COLORS = ['--tile-teal', '--tile-indigo', '--tile-purple']

function script(): Line[][] {
  const cards: Line[][] = [[{ text: APP_NAME, tone: 'title' }, { text: '致谢', tone: 'role' }]]
  CREDITS.forEach(({ group, items }, gi) => {
    cards.push([{ text: group, tone: 'group', color: GROUP_COLORS[gi % GROUP_COLORS.length] }])
    for (const [name, role] of items)
      cards.push([
        { text: name, tone: 'name' },
        { text: role, tone: 'role' },
      ])
  })
  cards.push([{ text: '以及读到这里的你', tone: 'name' }])
  return cards
}

const SIZES: Record<Tone, [number, number]> = {
  // [font px on the low-res canvas, weight]
  title: [24, 700],
  group: [15, 700],
  name: [15, 600],
  // CJK hairlines vanish at light weights once thresholded — keep it heavy
  role: [13, 600],
}

/** text → hard-edged pixel sprite in one color */
function sprite(text: string, tone: Tone, color: string): HTMLCanvasElement {
  const [size, weight] = SIZES[tone]
  const font = `${weight} ${size}px -apple-system, "PingFang SC", system-ui, sans-serif`
  const c = document.createElement('canvas')
  const m = c.getContext('2d')!
  m.font = font
  const w = Math.ceil(m.measureText(text).width) + 2
  const h = Math.ceil(size * 1.3)
  c.width = w
  c.height = h
  const g = c.getContext('2d')!
  g.font = font
  g.textBaseline = 'middle'
  g.fillStyle = color // only alpha matters; recolored below
  g.fillText(text, 1, h / 2)
  const img = g.getImageData(0, 0, w, h)
  const out = g.createImageData(w, h)
  const [r, gg, b] = parseColor(color)
  for (let i = 0; i < img.data.length; i += 4) {
    // low cut-off: thin horizontal CJK strokes antialias to ~40% alpha
    if (img.data[i + 3] > 60) {
      out.data[i] = r
      out.data[i + 1] = gg
      out.data[i + 2] = b
      out.data[i + 3] = 255
    }
  }
  g.putImageData(out, 0, 0)
  return c
}

function parseColor(css: string): [number, number, number] {
  const probe = document.createElement('canvas').getContext('2d')!
  probe.fillStyle = css
  probe.fillRect(0, 0, 1, 1)
  const d = probe.getImageData(0, 0, 1, 1).data
  return [d[0], d[1], d[2]]
}

interface Flyer {
  img: HTMLCanvasElement
  t0: number
  lane: number
  dist: number
}

export default function Credits({
  onClose,
  shot = false,
}: {
  onClose: () => void
  /** screenshot mode: no audio, start mid-roll */
  shot?: boolean
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const cvRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const root = rootRef.current
    const cv = cvRef.current
    if (!root || !cv) return
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    const cs = getComputedStyle(document.documentElement)
    const v = (name: string) => cs.getPropertyValue(name).trim()
    const ink = v('--egg-ink')
    const dim = v('--egg-dim')

    const music = shot ? null : new Chiptune()
    music?.start()

    const ctx = cv.getContext('2d')!
    const low = document.createElement('canvas')
    const lc = low.getContext('2d')!
    let W = 0
    let H = 0
    const fit = () => {
      cv.width = window.innerWidth
      cv.height = window.innerHeight
      W = Math.ceil(cv.width / PX)
      H = Math.ceil(cv.height / PX)
      low.width = W
      low.height = H
      ctx.imageSmoothingEnabled = false
    }
    fit()
    window.addEventListener('resize', fit)

    // cards: stacked line sprites, composed into one sprite each
    const cards = script().map((lines) => {
      const parts = lines.map((l) =>
        sprite(l.text, l.tone, l.color ? v(l.color) : l.tone === 'role' ? dim : ink)
      )
      const w = Math.max(...parts.map((p) => p.width))
      const h = parts.reduce((s, p) => s + p.height, 0)
      const c = document.createElement('canvas')
      c.width = w
      c.height = h
      const g = c.getContext('2d')!
      let y = 0
      for (const p of parts) {
        g.drawImage(p, 0, y)
        y += p.height
      }
      return c
    })
    const thanks = sprite('谢谢', 'title', ink)

    // one flight path; each card launches once the previous one has
    // cleared its own extent along the 30° line, so nothing overlaps
    const extent = (c: HTMLCanvasElement) => c.width * UX + c.height * -UY
    let along = 0
    const flyers: Flyer[] = cards.map((img, i) => {
      if (i > 0) along += extent(cards[i - 1]) / 2 + extent(img) / 2 + GAP
      return { img, t0: along / SPEED, lane: i % 2 ? 10 : -10, dist: 0 }
    })
    const stars = Array.from({ length: 140 }, () => ({
      x: Math.random(),
      y: Math.random(),
      z: 0.15 + Math.random() * 0.85, // parallax depth
      tw: Math.random() * Math.PI * 2,
    }))

    const offset = shot ? 9 : 0
    const start = performance.now()
    let raf = 0
    const half = () => Math.hypot(W, H) / 2

    const frame = (now: number) => {
      const t = (now - start) / 1000 + offset
      lc.clearRect(0, 0, W, H)

      // starfield drifting along the same 30° line
      for (const s of stars) {
        const d = reduced ? 0 : t * SPEED * 0.35 * s.z
        const x = (((s.x * W + UX * d) % W) + W) % W
        const y = (((s.y * H + UY * d) % H) + H) % H
        lc.globalAlpha = 0.25 + 0.5 * s.z * (0.6 + 0.4 * Math.sin(t * 3 + s.tw))
        lc.fillStyle = ink
        lc.fillRect(Math.round(x), Math.round(y), s.z > 0.8 ? 2 : 1, 1)
      }
      lc.globalAlpha = 1

      const cx = W / 2
      const cy = H / 2
      const D = half() + 80
      let alive = false
      if (reduced) {
        // still list, no flight
        let y = 16
        for (const img of cards) {
          if (y + img.height > H - 8) break
          lc.drawImage(img, Math.round(cx - img.width / 2), y)
          y += img.height + 4
        }
      } else {
        for (const f of flyers) {
          const s = (t - f.t0) * SPEED
          if (s < 0) {
            alive = true
            continue
          }
          if (s > 2 * D) continue
          alive = true
          const along = -D + s
          const x = cx + UX * along + NX * f.lane - f.img.width / 2
          const y = cy + UY * along + NY * f.lane - f.img.height / 2
          lc.drawImage(f.img, Math.round(x), Math.round(y))
        }
        if (!alive) {
          lc.drawImage(thanks, Math.round(cx - thanks.width / 2), Math.round(cy - thanks.height / 2))
        }
      }

      ctx.clearRect(0, 0, cv.width, cv.height)
      ctx.drawImage(low, 0, 0, W * PX, H * PX)
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'm' || e.key === 'M') music?.toggleMute()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', fit)
      window.removeEventListener('keydown', onKey)
      music?.stop()
    }
  }, [onClose, shot])

  return (
    <div ref={rootRef} className="credits" onClick={onClose} role="dialog" aria-label="致谢">
      <canvas ref={cvRef} className="credits-cv" />
      <div className="credits-hint t13">按 M 静音，按 Esc 或点击任意处返回</div>
    </div>
  )
}
