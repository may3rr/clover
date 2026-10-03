/** Footer dot field. A grid of dots; the ones that fall inside the icon's
 *  clover (same geometry as site/scripts/icon.mjs) take the four layer
 *  hues, the three trail dots take ink. A slow wave runs outward from the
 *  clover and dots swell near the pointer. Static under reduced motion. */

// icon geometry, in the icon's 1024 space
const CX = 494, CY = 486, A = 96, G = 13
const TRAIL: [number, number][] = [[262, 27], [326, 20], [382, 14]]
const LEAF_DIRS = [-90, 0, 90, 180] // up, right, down, left
const LEAF_VARS = ['--tile-indigo', '--tile-blue', '--tile-teal', '--tile-purple']
const R2 = A / Math.SQRT2

/** -1 outside, 0..3 leaf index, 4 trail */
function classify(x: number, y: number): number {
  const dx = x - CX, dy = y - CY
  for (let i = 0; i < 4; i++) {
    const t = (-LEAF_DIRS[i] * Math.PI) / 180
    // rotate the point into the leaf's frame (leaf points along +x)
    const u = dx * Math.cos(t) - dy * Math.sin(t) - G
    const v = dx * Math.sin(t) + dy * Math.cos(t)
    if (Math.abs(u - A) + Math.abs(v) <= A) return i // the square
    for (const s of [-1, 1]) {
      const cu = 1.5 * A, cv = (s * A) / 2
      if ((u - cu) ** 2 + (v - cv) ** 2 <= R2 * R2) return i
    }
  }
  for (const [d, r] of TRAIL) {
    const tx = CX + d / Math.SQRT2, ty = CY + d / Math.SQRT2
    if ((x - tx) ** 2 + (y - ty) ** 2 <= r * r) return 4
  }
  return -1
}

interface Dot {
  x: number
  y: number
  k: number // classify()
  d: number // distance from the clover centre, px
  fade: number // background dots thin out toward the edges
}

export function startField(canvas: HTMLCanvasElement) {
  const ctx = canvas.getContext('2d')!
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
  let dots: Dot[] = []
  let W = 0, H = 0, step = 12
  let colors: string[] = []
  let faint = ''
  const mouse = { x: -1e4, y: -1e4 }

  function readColors() {
    const cs = getComputedStyle(document.documentElement)
    colors = [...LEAF_VARS.map((v) => cs.getPropertyValue(v).trim()), cs.getPropertyValue('--text').trim()]
    faint = cs.getPropertyValue('--text-secondary').trim()
  }

  function layout() {
    const dpr = Math.min(devicePixelRatio || 1, 2)
    W = canvas.clientWidth
    H = canvas.clientHeight
    canvas.width = W * dpr
    canvas.height = H * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    step = W < 640 ? 9 : 12
    // clover spans ~580 icon units; fit it to 84% of the field's height
    const scale = (H * 0.84) / 580
    const ox = W / 2 - 500 * scale
    const oy = H / 2 - 492 * scale
    const cx = W / 2, cy = H / 2
    const maxD = Math.hypot(W / 2, H / 2)
    dots = []
    for (let y = step / 2; y < H; y += step)
      for (let x = step / 2; x < W; x += step) {
        const k = classify((x - ox) / scale, (y - oy) / scale)
        const d = Math.hypot(x - cx, y - cy)
        dots.push({ x, y, k, d, fade: 1 - Math.min(1, d / maxD) })
      }
  }

  function draw(t: number) {
    ctx.clearRect(0, 0, W, H)
    const time = t / 1000
    for (const p of dots) {
      const wave = reduced ? 0 : Math.sin(p.d / 46 - time * 1.4)
      const m = Math.hypot(p.x - mouse.x, p.y - mouse.y)
      const near = m < 110 ? 1 - m / 110 : 0
      let r: number
      if (p.k < 0) {
        r = 0.9 + 0.35 * wave * p.fade + near * 1.6
        ctx.globalAlpha = (0.1 + 0.22 * p.fade * p.fade) * (1 + near * 1.5)
        ctx.fillStyle = faint
      } else {
        r = (p.k === 4 ? 3.4 : 3.2) * (1 + 0.16 * wave) + near * 1.4
        ctx.globalAlpha = 1
        ctx.fillStyle = colors[p.k]
      }
      ctx.beginPath()
      ctx.arc(p.x, p.y, Math.max(0.4, Math.min(r, step / 2 - 0.4)), 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.globalAlpha = 1
  }

  let raf = 0
  let visible = false
  const loop = (t: number) => {
    draw(t)
    if (visible && !reduced) raf = requestAnimationFrame(loop)
  }
  const restart = () => {
    cancelAnimationFrame(raf)
    raf = requestAnimationFrame(loop)
  }

  readColors()
  layout()
  draw(0)
  new ResizeObserver(() => {
    layout()
    restart()
  }).observe(canvas)
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    readColors()
    restart()
  })
  new IntersectionObserver((e) => {
    visible = e[0].isIntersecting
    if (visible) restart()
  }).observe(canvas)
  canvas.addEventListener('pointermove', (e) => {
    const r = canvas.getBoundingClientRect()
    mouse.x = e.clientX - r.left
    mouse.y = e.clientY - r.top
    if (reduced) draw(0)
  })
  canvas.addEventListener('pointerleave', () => {
    mouse.x = mouse.y = -1e4
    if (reduced) draw(0)
  })
}
