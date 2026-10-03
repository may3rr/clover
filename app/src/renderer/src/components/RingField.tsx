import { useEffect, useRef } from 'react'

/** Generative dot field behind onboarding, in the spirit of "The
 * Intelligence Age": a few hundred dots that drift between formations —
 * scattered, concentric rings, an orbit around an element, a burst.
 * Every dot eases toward its target at its own rate, so changes ripple
 * through the field instead of snapping. Colors come from CSS tokens. */

export type FieldMode =
  | { kind: 'scatter' }
  | { kind: 'rings' }
  | { kind: 'halo' } // one wide, quiet ring framing the centre panel
  | { kind: 'orbit'; anchor: () => DOMRect | null; radius: number; tight?: boolean }
  | { kind: 'burst' }

interface Dot {
  x: number
  y: number
  a: number // current alpha
  ring: number // 0..2
  slot: number // 0..1 position along its ring
  size: number
  rate: number // easing rate toward target
  accent: boolean
  sx: number // scatter home (0..1)
  sy: number
  jitter: number
}

const N = 180
const RING_SHARE = [0.22, 0.33, 0.45] // dots per ring (inner → outer)

function makeDots(): Dot[] {
  const dots: Dot[] = []
  const counts = RING_SHARE.map((s) => Math.round(N * s))
  counts.forEach((c, ring) => {
    for (let k = 0; k < c; k++) {
      dots.push({
        x: Math.random(),
        y: Math.random(),
        a: 0,
        ring,
        slot: k / c,
        size: 1.2 + Math.random() * 2.2,
        rate: 0.025 + Math.random() * 0.06,
        accent: Math.random() < 0.07,
        sx: Math.random(),
        sy: Math.random(),
        jitter: Math.random() * 2 - 1,
      })
    }
  })
  return dots
}

export default function RingField({ mode }: { mode: FieldMode }) {
  const cvRef = useRef<HTMLCanvasElement>(null)
  const modeRef = useRef(mode)
  modeRef.current = mode

  useEffect(() => {
    const cv = cvRef.current
    if (!cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    // shot runs capture ~300ms after a state change: land formations at once
    const snap = reduced || window.citecheck.shotsMode
    let W = 0
    let H = 0
    let ink = ''
    let accent = ''
    const readColors = () => {
      const cs = getComputedStyle(document.documentElement)
      ink = cs.getPropertyValue('--text').trim()
      accent = cs.getPropertyValue('--accent').trim()
    }
    const fit = () => {
      const dpr = window.devicePixelRatio || 1
      W = cv.clientWidth
      H = cv.clientHeight
      cv.width = W * dpr
      cv.height = H * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    readColors()
    fit()
    const dots = makeDots()
    for (const d of dots) {
      d.x = d.sx * W
      d.y = d.sy * H
    }
    const dark = matchMedia('(prefers-color-scheme: dark)')
    dark.addEventListener('change', readColors)
    window.addEventListener('resize', fit)

    const t0 = performance.now()
    let raf = 0

    const target = (d: Dot, t: number): [number, number, number] => {
      const m = modeRef.current
      const S = Math.min(W, H)
      const cx = W / 2
      const cy = H / 2
      if (m.kind === 'scatter') return [d.sx * W, d.sy * H, 0.22]
      if (m.kind === 'burst') {
        const ang = d.slot * Math.PI * 2 + d.ring
        return [cx + Math.cos(ang) * S * 1.4, cy + Math.sin(ang) * S * 1.4, 0]
      }
      if (m.kind === 'rings') {
        const r = S * [0.2, 0.3, 0.41][d.ring]
        const dir = d.ring % 2 ? -1 : 1
        const speed = [0.05, 0.032, 0.022][d.ring]
        const ang = (d.slot + dir * speed * t) * Math.PI * 2
        const breathe = 1 + 0.025 * Math.sin(t * 0.9 + d.ring * 1.7)
        const rr = r * breathe + d.jitter * 3
        return [cx + Math.cos(ang) * rr, cy + Math.sin(ang) * rr, 0.42]
      }
      if (m.kind === 'halo') {
        const r = Math.max(W, H) * (0.36 + d.ring * 0.05)
        const ang = (d.slot + 0.008 * t * (d.ring % 2 ? -1 : 1)) * Math.PI * 2
        return [
          cx + Math.cos(ang) * r,
          cy + Math.sin(ang) * r * 0.82,
          0.16 + d.ring * 0.03,
        ]
      }
      // orbit around an element (avatar, lock)
      const rect = m.anchor()
      const ax = rect ? rect.left + rect.width / 2 : cx
      const ay = rect ? rect.top + rect.height / 2 : cy
      const spread = m.tight ? 6 : 14
      const r = m.radius + d.ring * spread + d.jitter * (m.tight ? 2 : 5)
      const speed = m.tight ? 0.06 : 0.035
      const ang = (d.slot + (d.ring % 2 ? -1 : 1) * speed * t) * Math.PI * 2
      return [ax + Math.cos(ang) * r, ay + Math.sin(ang) * r, m.tight ? 0.5 : 0.36]
    }

    const draw = (now: number) => {
      const t = (now - t0) / 1000
      ctx.clearRect(0, 0, W, H)
      for (const d of dots) {
        const [tx, ty, ta] = target(d, t)
        const k = snap ? 1 : d.rate
        d.x += (tx - d.x) * k
        d.y += (ty - d.y) * k
        d.a += (ta - d.a) * (snap ? 1 : 0.04)
        if (d.a < 0.01) continue
        ctx.globalAlpha = d.accent ? Math.min(1, d.a * 1.8) : d.a
        ctx.fillStyle = d.accent ? accent : ink
        ctx.beginPath()
        ctx.arc(d.x, d.y, d.size, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalAlpha = 1
      if (!reduced) raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    // reduced motion: repaint only when the formation changes
    const id = reduced ? setInterval(() => draw(performance.now()), 500) : 0

    return () => {
      cancelAnimationFrame(raf)
      if (id) clearInterval(id)
      dark.removeEventListener('change', readColors)
      window.removeEventListener('resize', fit)
    }
  }, [])

  return (
    <canvas
      ref={cvRef}
      aria-hidden
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
    />
  )
}
