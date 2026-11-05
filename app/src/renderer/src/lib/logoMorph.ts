/** 千问 ⇄ 英特尔 logo 变形的时间线与几何（纯函数，组件见
 *  components/QwenIntelMorph.tsx）。移植自 svg-transform/loading.html。
 *
 *  英特尔 logo 有 6 个可见形状，千问 3 块：千问每块分给两个英特尔拼块，
 *  用 flubber 逐对插值；e 的内孔在形变后段才从中心张开。一圈约 8 秒：
 *  千问转两圈 → 变成英特尔 → 字母依次弹跳、方点翻转 → 变回千问。 */

export const clamp01 = (x: number) => Math.min(1, Math.max(0, x))
export const easeInOutCubic = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
export const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3)
/** in-out with a small wind-up and overshoot */
export function easeInOutBack(t: number, c1 = 0.9): number {
  const c2 = c1 * 1.525
  return t < 0.5
    ? (Math.pow(2 * t, 2) * ((c2 + 1) * 2 * t - c2)) / 2
    : (Math.pow(2 * t - 2, 2) * ((c2 + 1) * (t * 2 - 2) + c2) + 2) / 2
}
/** damped oscillation after landing, 0 → 0 */
export const damped = (t: number, freq = 2.2, decay = 5) =>
  Math.exp(-decay * t) * Math.sin(t * Math.PI * 2 * freq)

/** '#rrggbb' (a CSS custom property's value) → [r, g, b] */
export function parseHex(h: string): [number, number, number] {
  const s = h.trim().replace(/^#/, '')
  const full = s.length === 3 ? [...s].map((c) => c + c).join('') : s
  const n = parseInt(full.slice(0, 6), 16)
  return Number.isNaN(n) ? [0, 0, 0] : [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export function mixHex(a: [number, number, number], b: [number, number, number], t: number): string {
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * t))
  return '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('')
}

export interface Box {
  x0: number
  x1: number
  y0: number
  y1: number
}

/** bounding box of an absolute-coordinate path (x,y pairs only) */
export function bbox(d: string): Box {
  const n = (d.match(/-?\d*\.?\d+/g) ?? []).map(Number)
  const xs = n.filter((_, i) => i % 2 === 0)
  const ys = n.filter((_, i) => i % 2 === 1)
  return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) }
}

/** scale an absolute-coordinate path about (cx, cy) */
export function scalePath(d: string, k: number, cx: number, cy: number): string {
  let i = 0
  return d.replace(/-?\d*\.?\d+/g, (v) => {
    const c = i++ % 2 === 0 ? cx : cy
    return (c + (Number(v) - c) * k).toFixed(2)
  })
}

export type Role = 'dot' | 'letter'
/** [intel piece, qwen piece it grows from, colour], left to right */
export const PIECE_MAP: { i: number; q: number; tone: 'dot' | 'letter'; role: Role; hole?: number }[] = [
  { i: 0, q: 1, tone: 'dot', role: 'dot' },
  { i: 1, q: 1, tone: 'letter', role: 'letter' },
  { i: 4, q: 0, tone: 'letter', role: 'letter' },
  { i: 2, q: 0, tone: 'letter', role: 'letter' },
  { i: 5, q: 2, tone: 'letter', role: 'letter', hole: 6 },
  { i: 3, q: 2, tone: 'letter', role: 'letter' },
]

export const T = {
  spin: 1900, // 千问转两圈
  hold1: 250,
  morph: 1300, // 千问 → 英特尔
  intel: 2300, // 英特尔自身动画
  hold2: 250,
  back: 1300, // 英特尔 → 千问
  hold3: 350,
} as const
export type Stage = keyof typeof T
const STAGES = Object.entries(T) as [Stage, number][]
export const LOOP = STAGES.reduce((s, [, v]) => s + v, 0)
const STAGGER = 70

/** which stage the loop is in at elapsed ms, and the ms into it */
export function stageAt(elapsed: number): { stage: Stage; local: number } {
  let e = ((elapsed % LOOP) + LOOP) % LOOP
  for (const [stage, dur] of STAGES) {
    if (e < dur) return { stage, local: e }
    e -= dur
  }
  return { stage: 'hold3', local: 0 }
}

/** morph progress, 0 = qwen, 1 = intel; pieces start STAGGER ms apart */
export function morphT(local: number, dur: number, idx: number, n: number, reverse: boolean): number {
  const span = dur - STAGGER * (n - 1)
  const order = reverse ? n - 1 - idx : idx
  return easeInOutCubic(clamp01((local - order * STAGGER) / span))
}

/** intel stage: letters hop one after another, the dot crouches, jumps,
 *  flips half a turn and lands with a squash */
export function intelTransform(role: Role, b: Box, idx: number, local: number): string {
  const cx = (b.x0 + b.x1) / 2
  const h = b.y1 - b.y0
  let ty = 0
  let sx = 1
  let sy = 1
  let rot = 0
  if (role === 'letter') {
    const start = 80 + (idx - 1) * 95
    const air = 460
    const settle = 520
    const t = local - start
    if (t > 0 && t < air) {
      const u = t / air
      ty = -9 * 4 * u * (1 - u)
      const s = Math.sin(Math.PI * u)
      sy = 1 + 0.1 * s
      sx = 1 - 0.05 * s
    } else if (t >= air && t < air + settle) {
      const k = damped((t - air) / settle, 1.6, 4.5)
      sy = 1 - 0.16 * k
      sx = 1 + 0.1 * k
    }
  } else {
    const crouch = 180
    const air = 720
    const settle = 620
    const t = local - 640
    if (t > 0 && t < crouch) {
      const s = Math.sin((Math.PI / 2) * (t / crouch))
      sy = 1 - 0.28 * s
      sx = 1 + 0.2 * s
    } else if (t >= crouch && t < crouch + air) {
      const u = (t - crouch) / air
      ty = -30 * 4 * u * (1 - u)
      rot = 180 * easeInOutCubic(u)
      const s = Math.sin(Math.PI * Math.min(1, u * 2.2))
      sy = 1 + 0.18 * s * (1 - u)
      sx = 1 - 0.1 * s * (1 - u)
      if (u < 0.12) {
        const r = 1 - u / 0.12
        sy -= 0.28 * r * r
        sx += 0.2 * r * r
      }
    } else if (t >= crouch + air && t < crouch + air + settle) {
      const k = damped((t - crouch - air) / settle, 2, 5)
      sy = 1 - 0.3 * k
      sx = 1 + 0.22 * k
    }
  }
  if (!ty && !rot && sx === 1 && sy === 1) return ''
  return `translate(${cx} ${b.y1 + ty}) translate(0 ${-h / 2}) rotate(${rot}) translate(0 ${h / 2}) scale(${sx} ${sy}) translate(${-cx} ${-b.y1})`
}

/** whole-logo transform during the spin stage */
export function spinTransform(local: number): string {
  const u = local / T.spin
  const a = 720 * easeInOutBack(u)
  const s = 1 - 0.07 * Math.sin(Math.PI * u)
  return `translate(70 50) rotate(${a}) scale(${s}) translate(-70 -50)`
}

/** per-piece morph progress (0 qwen … 1 intel) for a stage */
export function pieceT(stage: Stage, local: number, idx: number, n: number): number {
  switch (stage) {
    case 'morph':
      return morphT(local, T.morph, idx, n, false)
    case 'intel':
    case 'hold2':
      return 1
    case 'back':
      return 1 - morphT(local, T.back, idx, n, true)
    default:
      return 0
  }
}

/** how far the e's counter has opened at morph progress t */
export const holeK = (t: number) => easeOutCubic(clamp01((t - 0.6) / 0.4))
