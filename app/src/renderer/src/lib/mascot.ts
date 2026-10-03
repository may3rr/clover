/**
 * Mascot engine: the pose-and-motion system behind components/Mascot.tsx.
 *
 * Ported from the animation prototype (orb.html). The head and eye geometry
 * and the animation model are kept as designed:
 *   - every channel is a delta from the rest pose (rest pose = all zeros), so
 *     one-shot actions stack on top of looping states;
 *   - states loop (first key = last key) and are interpolated with periodic
 *     Catmull-Rom, so the loop seam is velocity-continuous;
 *   - switching state cross-fades the weights (snapshot + smoothstep), so a
 *     switch interrupted halfway never pops;
 *   - actions are one-shot (first and last key are 0);
 *   - a stance is a slow overlay (support / doubt) that follows the verdict,
 *     independent of what the agent is doing.
 * Only the clips Clover uses are kept. One shared rAF loop drives every
 * mascot on screen (see the manager at the bottom).
 */

// ---------------------------------------------------------------- geometry

export const HEAD_D =
  'M228.541 114.228C228.541 130.133 225.184 145.994 218.738 160.534C212.674 174.217 203.904 186.669 193.065 196.988C155.933 232.34 99.497 238.596 55.5255 212.24C45.097 205.99 35.6851 198.072 27.7451 188.866C19.1926 178.953 12.3686 167.569 7.65781 155.351C2.60712 142.264 0 128.257 0 114.228C0 98.3219 3.35751 82.4611 9.80315 67.9215C15.8672 54.2382 24.6377 41.7862 35.4767 31.4668C72.6081 -3.88483 129.044 -10.1413 173.016 16.2153C183.444 22.4653 192.856 30.3829 200.796 39.5896C209.349 49.5018 216.173 60.8859 220.883 73.1037C225.934 86.1906 228.541 100.198 228.541 114.228Z'
export const EYE_D =
  'M148.55 66.73C148.81 67.26 149.08 67.80 149.40 68.41C149.71 69.03 150.03 69.67 150.41 70.43C150.79 71.19 151.33 72.05 151.69 72.97C152.05 73.89 152.41 74.93 152.56 75.93C152.70 76.93 152.69 77.97 152.55 78.95C152.41 79.94 152.12 80.92 151.71 81.82C151.31 82.71 150.75 83.58 150.12 84.32C149.49 85.07 148.72 85.75 147.91 86.29C147.10 86.83 146.18 87.27 145.25 87.56C144.32 87.86 143.32 88.03 142.34 88.06C141.36 88.09 140.34 87.98 139.39 87.74C138.44 87.49 137.48 87.11 136.62 86.60C135.77 86.10 134.94 85.45 134.26 84.71C133.57 83.97 132.99 83.00 132.49 82.17C131.98 81.34 131.62 80.45 131.25 79.71C130.87 78.98 130.56 78.35 130.26 77.75C129.96 77.15 129.69 76.62 129.43 76.11C129.17 75.59 128.93 75.12 128.70 74.66C128.46 74.19 128.24 73.76 128.03 73.33C127.81 72.90 127.60 72.48 127.39 72.06C127.18 71.64 126.97 71.24 126.76 70.82C126.55 70.40 126.34 69.98 126.12 69.55C125.90 69.11 125.68 68.67 125.44 68.20C125.20 67.73 124.96 67.26 124.70 66.73C124.43 66.21 124.16 65.67 123.85 65.05C123.54 64.43 123.22 63.80 122.83 63.04C122.45 62.28 121.91 61.41 121.56 60.49C121.20 59.57 120.83 58.53 120.69 57.53C120.54 56.53 120.55 55.49 120.69 54.51C120.83 53.53 121.13 52.54 121.53 51.64C121.94 50.75 122.49 49.88 123.12 49.14C123.76 48.40 124.52 47.72 125.33 47.18C126.14 46.64 127.06 46.20 127.99 45.90C128.92 45.60 129.93 45.43 130.91 45.40C131.88 45.37 132.90 45.48 133.86 45.72C134.81 45.97 135.77 46.36 136.62 46.86C137.48 47.37 138.30 48.01 138.99 48.75C139.68 49.49 140.26 50.46 140.76 51.29C141.26 52.13 141.63 53.02 142.00 53.75C142.37 54.49 142.68 55.11 142.99 55.71C143.29 56.31 143.56 56.84 143.82 57.36C144.08 57.87 144.31 58.34 144.55 58.81C144.78 59.27 145.00 59.70 145.22 60.13C145.44 60.57 145.65 60.98 145.86 61.40C146.07 61.82 146.27 62.23 146.49 62.65C146.70 63.07 146.91 63.48 147.13 63.92C147.35 64.35 147.57 64.79 147.80 65.26C148.04 65.73 148.28 66.21 148.55 66.73Z'

export const CX = 114.27
export const CY = 114.27
export const BOTTOM = 228.54
const EYE_Y = 104
const EYE_HALF = 28
const EYE_BASE = 1.18

/** Room around the head for jumps and the ground shadow (SVG viewBox). */
export const VIEWBOX = { x: -40, y: -84, w: 308.5, h: 380 }
/** Width of the head itself in viewBox units; `size` props are in head widths. */
export const HEAD_W = 228.541

// ---------------------------------------------------------------- channels

type Channel =
  | 'bx' | 'by' | 'brot' | 'bsx' | 'bsy'
  | 'lx' | 'ly' | 'esx' | 'esy'
  | 'blink' | 'winkL' | 'winkR' | 'etilt' | 'lid' | 'gap'
type Pose = Partial<Record<Channel, number>>

type EaseName = 'lin' | 'i2' | 'o2' | 'io2' | 'io3'
const EASE: Record<EaseName, (t: number) => number> = {
  lin: (t) => t,
  i2: (t) => t * t,
  o2: (t) => 1 - (1 - t) * (1 - t),
  io2: (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2),
  io3: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
}
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v))

/** [time 0..1, value, ease to the next key] */
type Key = [number, number] | [number, number, EaseName]
type Track = Partial<Record<Channel, Key[]>>
const hold = (v: number): Key[] => [[0, v], [0.5, v], [1, v]]

// ---------------------------------------------------------------- clips

export type MascotState =
  | 'idle'
  | 'thinking'
  | 'reading'
  | 'happy'
  | 'worried'
  | 'sleep'
export type MascotAction = 'blink' | 'nod' | 'bounce' | 'pulse'
export type MascotStance = 'none' | 'support' | 'doubt'

interface StateClip {
  label: string
  dur: number
  keys: Track
}
interface ActionClip {
  label: string
  dur: number
  keys: Track
}

// States loop. Every track's first key equals its last key.
export const STATES: Record<MascotState, StateClip> = {
  idle: {
    label: '待机',
    dur: 4.2,
    keys: {
      by: [[0, 0], [0.5, -3], [1, 0]],
      bsy: [[0, 0], [0.5, 0.014], [1, 0]],
      bsx: [[0, 0], [0.5, -0.008], [1, 0]],
      lx: [[0, 0], [0.3, 4], [0.55, 0], [0.8, -4], [1, 0]],
      ly: [[0, 0], [0.5, -1.5], [1, 0]],
      brot: [[0, 0], [0.3, 1.2], [0.7, -1.2], [1, 0]],
    },
  },
  thinking: {
    label: '思考',
    dur: 5.5,
    keys: {
      lx: [[0, -13], [0.28, -13], [0.5, 12], [0.78, 12], [1, -13]],
      ly: hold(-14),
      brot: [[0, -4], [0.5, 4], [1, -4]],
      by: [[0, 0], [0.5, -2], [1, 0]],
      esy: hold(-0.05),
      etilt: hold(-5),
    },
  },
  happy: {
    label: '开心',
    dur: 1.1,
    keys: {
      by: [[0, 0], [0.3, -10], [0.55, 0], [0.7, -3], [0.85, 0], [1, 0]],
      bsy: [[0, -0.04], [0.15, -0.07], [0.3, 0.06], [0.55, -0.06], [1, -0.04]],
      bsx: [[0, 0.03], [0.15, 0.05], [0.3, -0.04], [0.55, 0.05], [1, 0.03]],
      esy: hold(-0.28),
      esx: hold(0.12),
      ly: hold(-3),
    },
  },
  worried: {
    label: '担忧',
    dur: 3.6,
    keys: {
      etilt: hold(-16),
      ly: hold(9),
      by: [[0, 3], [0.5, 4.5], [1, 3]],
      bsy: hold(-0.03),
      brot: [[0, -3], [0.5, 3], [1, -3]],
      lx: [[0, -5], [0.5, 5], [1, -5]],
      esy: hold(0.05),
    },
  },
  sleep: {
    label: '睡着',
    dur: 5.5,
    keys: {
      lid: hold(0.9),
      by: [[0, 3], [0.5, 6], [1, 3]],
      bsy: [[0, -0.02], [0.5, 0.02], [1, -0.02]],
      brot: hold(4),
      ly: hold(6),
    },
  },
  // eyes sweep along lines of text, then return to the start of the next
  reading: {
    label: '读材料',
    dur: 2.6,
    keys: {
      lx: [[0, -14], [0.36, 14], [0.44, -14], [0.8, 14], [0.88, -14], [1, -14]],
      ly: [[0, 7], [0.44, 10], [0.88, 13], [1, 7]],
      brot: [[0, -2], [0.5, 2], [1, -2]],
      by: [[0, 0], [0.5, -1.5], [1, 0]],
      esy: hold(-0.04),
    },
  },
}

// Actions are one-shot. First and last key of every track are 0.
export const ACTIONS: Record<MascotAction, ActionClip> = {
  blink: {
    label: '眨眼',
    dur: 0.18,
    keys: { blink: [[0, 0, 'io2'], [0.42, 1, 'io2'], [1, 0]] },
  },
  bounce: {
    label: '小跳',
    dur: 0.46,
    keys: {
      by: [[0, 0, 'o2'], [0.3, -16, 'i2'], [0.62, 2, 'o2'], [0.8, -2, 'io2'], [1, 0]],
      bsy: [[0, 0, 'io2'], [0.1, -0.07, 'o2'], [0.3, 0.06, 'io2'], [0.6, -0.08, 'io2'], [0.8, 0.02, 'io2'], [1, 0]],
      bsx: [[0, 0, 'io2'], [0.1, 0.05, 'o2'], [0.3, -0.04, 'io2'], [0.6, 0.06, 'io2'], [0.8, -0.015, 'io2'], [1, 0]],
    },
  },
  nod: {
    label: '点头',
    dur: 0.62,
    keys: {
      by: [[0, 0, 'io2'], [0.22, 5, 'io2'], [0.44, -1, 'io2'], [0.66, 4, 'io2'], [1, 0]],
      brot: [[0, 0, 'io2'], [0.22, 4, 'io2'], [0.44, -1, 'io2'], [0.66, 3, 'io2'], [1, 0]],
      ly: [[0, 0, 'io2'], [0.22, 6, 'io2'], [0.44, -1, 'io2'], [0.66, 5, 'io2'], [1, 0]],
      bsy: [[0, 0, 'io2'], [0.22, -0.05, 'io2'], [0.44, 0.01, 'io2'], [0.66, -0.04, 'io2'], [1, 0]],
    },
  },
  pulse: {
    label: '亮起',
    dur: 0.7,
    keys: {
      esx: [[0, 0, 'o2'], [0.2, 0.18, 'io2'], [1, 0]],
      esy: [[0, 0, 'o2'], [0.2, 0.18, 'io2'], [1, 0]],
      by: [[0, 0, 'o2'], [0.25, -8, 'i2'], [0.5, 0, 'o2'], [0.65, -1.5, 'io2'], [1, 0]],
    },
  },
}

// Stances overlay the current state. They come from the verdict, not a mood.
export const STANCES: Record<MascotStance, { label: string; v: Pose }> = {
  none: { label: '无', v: {} },
  support: { label: '支持', v: { esy: -0.12, esx: 0.05, ly: -1.5 } },
  doubt: { label: '存疑', v: { etilt: -14, ly: 6, esy: 0.04 } },
}

// ---------------------------------------------------------------- sampling

interface Ring {
  ts: number[]
  vs: number[]
  m: number[]
  n: number
}
type PreparedState = StateClip & { tr: Partial<Record<Channel, Ring>> }

/** Tangents for the periodic Catmull-Rom of each state track (done once). */
const PREPARED: Record<string, PreparedState> = {}
for (const [name, st] of Object.entries(STATES)) {
  const tr: Partial<Record<Channel, Ring>> = {}
  for (const [ch, keys] of Object.entries(st.keys) as [Channel, Key[]][]) {
    const ring = keys.slice(0, -1) // drop the last key, it repeats the first
    const ts = ring.map((k) => k[0])
    const vs = ring.map((k) => k[1])
    const n = ts.length
    const m = new Array<number>(n)
    for (let i = 0; i < n; i++) {
      const p = (i - 1 + n) % n
      const q = (i + 1) % n
      const tp = i === 0 ? ts[n - 1] - 1 : ts[p]
      const tq = i === n - 1 ? 1 : ts[q]
      m[i] = (vs[q] - vs[p]) / (tq - tp)
    }
    tr[ch] = { ts, vs, m, n }
  }
  PREPARED[name] = { ...st, tr }
}

export function sampleState(
  name: MascotState,
  tSec: number,
  out: Pose,
  w: number
): void {
  const st = PREPARED[name]
  const u = (((tSec / st.dur) % 1) + 1) % 1
  for (const ch of Object.keys(st.tr) as Channel[]) {
    const { ts, vs, m, n } = st.tr[ch] as Ring
    let i = n - 1
    for (let k = 0; k < n - 1; k++) {
      if (u >= ts[k] && u < ts[k + 1]) {
        i = k
        break
      }
    }
    const t0 = ts[i]
    const t1 = i === n - 1 ? 1 : ts[i + 1]
    const j = (i + 1) % n
    const h = t1 - t0
    const s = (u - t0) / h
    const s2 = s * s
    const s3 = s2 * s
    const v =
      (2 * s3 - 3 * s2 + 1) * vs[i] +
      (s3 - 2 * s2 + s) * h * m[i] +
      (-2 * s3 + 3 * s2) * vs[j] +
      (s3 - s2) * h * m[j]
    out[ch] = (out[ch] ?? 0) + v * w
  }
}

export function sampleAction(
  name: MascotAction,
  tSec: number,
  out: Pose,
  w: number
): void {
  const ac = ACTIONS[name]
  const u = tSec / ac.dur
  if (u >= 1) return
  for (const ch of Object.keys(ac.keys) as Channel[]) {
    const keys = ac.keys[ch] as Key[]
    let i = keys.length - 2
    for (let k = 0; k < keys.length - 1; k++) {
      if (u >= keys[k][0] && u < keys[k + 1][0]) {
        i = k
        break
      }
    }
    const a = keys[i]
    const b = keys[i + 1]
    const s = (u - a[0]) / (b[0] - a[0])
    const ease = EASE[(a[2] as EaseName | undefined) ?? 'io2']
    const v = a[1] + (b[1] - a[1]) * ease(s)
    out[ch] = (out[ch] ?? 0) + v * w
  }
}

/** Clip sanity: states loop seamlessly, actions start and end at rest. */
export function validateClips(): string[] {
  const bad: string[] = []
  const eq = (a: number, b: number) => Math.abs(a - b) < 1e-9
  for (const [name, st] of Object.entries(STATES)) {
    for (const [ch, keys] of Object.entries(st.keys) as [Channel, Key[]][]) {
      if (!eq(keys[0][0], 0) || !eq(keys[keys.length - 1][0], 1))
        bad.push(`state ${name}.${ch}: time must span 0..1`)
      if (!eq(keys[0][1], keys[keys.length - 1][1]))
        bad.push(`state ${name}.${ch}: first and last key differ`)
      if (keys.length < 3) bad.push(`state ${name}.${ch}: fewer than 3 keys`)
    }
  }
  for (const [name, ac] of Object.entries(ACTIONS)) {
    for (const [ch, keys] of Object.entries(ac.keys) as [Channel, Key[]][]) {
      if (!eq(keys[0][0], 0) || !eq(keys[keys.length - 1][0], 1))
        bad.push(`action ${name}.${ch}: time must span 0..1`)
      if (!eq(keys[0][1], 0) || !eq(keys[keys.length - 1][1], 0))
        bad.push(`action ${name}.${ch}: must start and end at 0`)
    }
  }
  return bad
}

// ---------------------------------------------------------------- eye metrics

export interface EyeMetrics {
  center: [number, number]
  /** rotation that stands the hand-drawn eye upright */
  upright: number
  height: number
}
let eyeMetrics: EyeMetrics | null = null

/** Bounding box centre and principal axis of the drawn eye (measured once). */
export function getEyeMetrics(): EyeMetrics {
  if (eyeMetrics) return eyeMetrics
  const NS = 'http://www.w3.org/2000/svg'
  const probe = document.createElementNS(NS, 'svg')
  probe.setAttribute('style', 'position:absolute;visibility:hidden;width:0;height:0')
  const p = document.createElementNS(NS, 'path')
  p.setAttribute('d', EYE_D)
  probe.appendChild(p)
  document.body.appendChild(probe)
  const bb = p.getBBox()
  const len = p.getTotalLength()
  const pts: [number, number][] = []
  for (let i = 0; i < 240; i++) {
    const q = p.getPointAtLength((len * i) / 240)
    pts.push([q.x, q.y])
  }
  document.body.removeChild(probe)
  const mx = pts.reduce((s, q) => s + q[0], 0) / pts.length
  const my = pts.reduce((s, q) => s + q[1], 0) / pts.length
  let sxx = 0
  let syy = 0
  let sxy = 0
  for (const [x, y] of pts) {
    sxx += (x - mx) ** 2
    syy += (y - my) ** 2
    sxy += (x - mx) * (y - my)
  }
  const theta = 0.5 * Math.atan2(2 * sxy, sxx - syy)
  let fromVertical = (theta * 180) / Math.PI - 90
  if (fromVertical < -90) fromVertical += 180
  eyeMetrics = {
    center: [bb.x + bb.width / 2, bb.y + bb.height / 2],
    upright: -fromVertical,
    height: bb.height,
  }
  return eyeMetrics
}

// ---------------------------------------------------------------- engine

export interface MascotEls {
  shadow: SVGElement
  body: SVGElement
  eyes: SVGElement
  eyeL: SVGElement
  eyeR: SVGElement
}

interface Layer {
  name: MascotState
  t: number
  w: number
  base: number
}
interface Playing {
  name: MascotAction
  t: number
  fade: number
  fading: boolean
}

export class MascotEngine {
  private layers: Layer[] = []
  private actions: Playing[] = []
  private blend = 0.45
  private r = 1
  private blinkTimer = 2 + Math.random() * 2
  private sv: Pose = {}
  private stanceName: MascotStance = 'none'
  private stateName: MascotState | null = null
  /** reduced motion: static rest pose per state, changes jump */
  reduced = false

  constructor(
    private els: MascotEls,
    private eye: EyeMetrics,
    phase = 0
  ) {
    this.setState('idle', true)
    this.layers[0].t = phase * STATES.idle.dur
  }

  get state(): MascotState | null {
    return this.stateName
  }

  setState(name: MascotState, instant = false): void {
    if (this.stateName === name) return
    if (instant || this.reduced || !this.layers.length) {
      this.layers = [{ name, t: 0, w: 1, base: 1 }]
      this.r = 1
    } else {
      // snapshot the old weights (they sum to 1); the new layer then grows by
      // smoothstep while the old ones shrink in proportion. A switch that is
      // interrupted halfway stays continuous.
      for (const l of this.layers) l.base = l.w
      this.layers.push({ name, t: 0, w: 0, base: 0 })
      this.r = 0
    }
    this.stateName = name
    if (this.reduced) this.renderStatic()
  }

  setStance(name: MascotStance): void {
    this.stanceName = name
    if (this.reduced) this.renderStatic()
  }

  play(name: MascotAction): void {
    if (this.reduced) return
    for (const a of this.actions) if (a.name === name) a.fading = true
    this.actions.push({ name, t: 0, fade: 1, fading: false })
  }

  /** Static pose for reduced motion: the first frame of the state plus the stance. */
  renderStatic(): void {
    const p: Pose = {}
    if (this.stateName) sampleState(this.stateName, 0, p, 1)
    this.sv = { ...STANCES[this.stanceName].v }
    for (const [ch, v] of Object.entries(this.sv) as [Channel, number][])
      p[ch] = (p[ch] ?? 0) + v
    this.render(p)
  }

  tick(dt: number): void {
    // 1. state layers
    this.r = Math.min(1, this.r + dt / this.blend)
    const d = this.r * this.r * (3 - 2 * this.r)
    const last = this.layers.length - 1
    this.layers.forEach((l, i) => {
      l.t += dt
      l.w = i === last ? d : l.base * (1 - d)
    })
    if (this.r >= 1 && last > 0) {
      this.layers = [this.layers[last]]
      this.layers[0].w = 1
    }
    const p: Pose = {}
    for (const l of this.layers) sampleState(l.name, l.t, p, l.w)
    // 2. one-shot actions stack on top
    for (const a of this.actions) {
      a.t += dt
      if (a.fading) a.fade = Math.max(0, a.fade - dt / 0.15)
      sampleAction(a.name, a.t, p, a.fade)
    }
    this.actions = this.actions.filter(
      (a) => a.t < ACTIONS[a.name].dur && a.fade > 0
    )
    // 3. stance: exponential approach to the target vector (~0.25 s)
    const tv = STANCES[this.stanceName].v
    const ks = 1 - Math.exp(-dt * 8)
    const chans = new Set([
      ...(Object.keys(this.sv) as Channel[]),
      ...(Object.keys(tv) as Channel[]),
    ])
    for (const ch of chans) {
      const cur = this.sv[ch] ?? 0
      const nxt = cur + ((tv[ch] ?? 0) - cur) * ks
      if (Math.abs(nxt) < 1e-4 && !(ch in tv)) delete this.sv[ch]
      else this.sv[ch] = nxt
      p[ch] = (p[ch] ?? 0) + (this.sv[ch] ?? 0)
    }
    // 4. auto blink (not while asleep)
    this.blinkTimer -= dt
    if (this.stateName !== 'sleep' && this.blinkTimer <= 0) {
      this.play('blink')
      this.blinkTimer = 2.2 + Math.random() * 3.6
    }
    this.render(p)
  }

  private render(p: Pose): void {
    const v = (c: Channel) => p[c] ?? 0
    const e = this.els
    const f = (x: number) => x.toFixed(2)
    const sx = 1 + v('bsx')
    const sy = 1 + v('bsy')
    e.body.setAttribute(
      'transform',
      `translate(${f(v('bx'))} ${f(v('by'))}) translate(${CX} ${BOTTOM}) scale(${f(sx)} ${f(sy)}) translate(${-CX} ${-BOTTOM}) rotate(${f(v('brot'))} ${CX} ${CY})`
    )
    // the ground shadow shrinks and fades as the body rises
    const up = Math.max(0, -v('by'))
    e.shadow.setAttribute('rx', f(80 * (1 + v('bsx') * 0.8) * (1 - up / 300)))
    e.shadow.setAttribute('opacity', f(clamp(1 - up / 110, 0.25, 1)))
    e.eyes.setAttribute('transform', `translate(${f(v('lx'))} ${f(v('ly'))})`)
    const lidF = 1 - 0.72 * clamp(v('lid'), 0, 1)
    for (const s of [-1, 1]) {
      const g = s < 0 ? e.eyeL : e.eyeR
      const cl = clamp(v('blink') + (s < 0 ? v('winkL') : v('winkR')), 0, 1)
      const esx = EYE_BASE * (1 + v('esx'))
      const esy0 = EYE_BASE * (1 + v('esy'))
      const esy = Math.max(0.03, esy0 * (1 - 0.95 * cl) * lidF)
      // lids close from the top: keep the lower edge of the eye fixed
      const dy = ((esy0 * (1 - 0.95 * cl) - esy) * this.eye.height) / 2
      const cx = CX + s * (EYE_HALF + v('gap'))
      const cy = EYE_Y + dy
      // order: stand the drawn eye upright, scale in that frame, then tilt
      // (non-uniform scale on the tilted original would shear it)
      g.setAttribute(
        'transform',
        `translate(${f(cx)} ${f(cy)}) rotate(${f(s * v('etilt'))}) scale(${f(esx)} ${f(esy)}) rotate(${f(this.eye.upright)})`
      )
    }
  }
}

// ---------------------------------------------------------------- manager

// One rAF loop for every mascot on screen. It runs only while at least one
// animated mascot is mounted and the page is visible.
const live = new Set<MascotEngine>()
let raf = 0
let prev = 0

const reducedMq =
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null
export const prefersReducedMotion = () => reducedMq?.matches ?? false

function frame(now: number) {
  raf = 0
  const dt = Math.min(0.05, (now - prev) / 1000)
  prev = now
  for (const m of live) if (!m.reduced) m.tick(dt)
  schedule()
}
function schedule() {
  if (raf || document.hidden) return
  for (const m of live) {
    if (!m.reduced) {
      prev = performance.now()
      raf = requestAnimationFrame(frame)
      return
    }
  }
}
function stop() {
  if (raf) cancelAnimationFrame(raf)
  raf = 0
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop()
    else schedule()
  })
  reducedMq?.addEventListener('change', () => {
    for (const m of live) {
      m.reduced = reducedMq.matches
      if (m.reduced) m.renderStatic()
    }
    if (reducedMq.matches) stop()
    else schedule()
  })
}

/** Add an engine to the shared loop. Returns the function that removes it. */
export function attachMascot(m: MascotEngine): () => void {
  m.reduced = prefersReducedMotion()
  live.add(m)
  if (m.reduced) m.renderStatic()
  else {
    m.tick(0) // first pose now, not one frame late
    schedule()
  }
  return () => {
    live.delete(m)
    if (live.size === 0) stop()
  }
}

// ---------------------------------------------------------------- roster

/** One fixed color per agent; a color never changes with state. */
export const AGENT_COLOR: Record<string, string> = {
  authenticity: 'var(--tile-indigo)',
  support: 'var(--tile-blue)',
  distribution: 'var(--tile-teal)',
  norms: 'var(--tile-purple)',
  overview: 'var(--tile-pink)',
}
