/** 8-bit arrangement of Beethoven's "Ode to Joy" (Symphony No. 9, 1824 —
 * public domain) for the credits easter egg, synthesized live with
 * WebAudio: 25% pulse lead, triangle bass, soft noise hats. Kept quiet on
 * purpose — it should be fine to open in a lecture hall. */

const BPM = 112
const STEP = 60 / BPM / 2 // one eighth note

// melody as [MIDI note, length in eighths]; C5 = 72
const C = 72, D = 74, E = 76, F = 77, G = 79, Gl = 67
const A_HEAD: [number, number][] = [
  [E, 2], [E, 2], [F, 2], [G, 2],
  [G, 2], [F, 2], [E, 2], [D, 2],
  [C, 2], [C, 2], [D, 2], [E, 2],
]
const PHRASE_A = [...A_HEAD, [E, 3], [D, 1], [D, 4]] as [number, number][]
const PHRASE_A2 = [...A_HEAD, [D, 3], [C, 1], [C, 4]] as [number, number][]
const PHRASE_B: [number, number][] = [
  [D, 2], [D, 2], [E, 2], [C, 2],
  [D, 2], [E, 1], [F, 1], [E, 2], [C, 2],
  [D, 2], [E, 1], [F, 1], [E, 2], [D, 2],
  [C, 2], [D, 2], [Gl, 4],
]
const MELODY = [...PHRASE_A, ...PHRASE_A2, ...PHRASE_B, ...PHRASE_A2]

// one bass root per bar (8 eighths), C3 = 48 / G2 = 43
const Cb = 48, Gb = 43
const ROOTS = [
  Cb, Gb, Cb, Gb, // A
  Cb, Gb, Cb, Cb, // A'
  Gb, Cb, Gb, Gb, // B
  Cb, Gb, Cb, Cb, // A'
]
const BASS_SHAPE = [0, -1, 12, -1, 7, -1, 12, -1] // -1 = rest

/** master level: audible, never loud */
const VOLUME = 0.035

const hz = (m: number) => 440 * Math.pow(2, (m - 69) / 12)

export class Chiptune {
  private ctx: AudioContext | null = null
  private master: GainNode | null = null
  private pulse: PeriodicWave | null = null
  private noise: AudioBuffer | null = null
  private timer = 0
  private nextAt = 0
  private step = 0 // eighth-note counter, loops over the whole tune
  private melodyIdx = 0
  private melodyNextStep = 0
  private muted = false

  start() {
    const ctx = new AudioContext()
    this.ctx = ctx
    // a limiter after the master gain, so overlapping voices can't spike
    const limiter = ctx.createDynamicsCompressor()
    limiter.threshold.value = -24
    limiter.knee.value = 0
    limiter.ratio.value = 20
    limiter.attack.value = 0.003
    limiter.release.value = 0.1
    limiter.connect(ctx.destination)
    const master = ctx.createGain()
    master.gain.setValueAtTime(0, ctx.currentTime)
    master.gain.linearRampToValueAtTime(VOLUME, ctx.currentTime + 1.2)
    master.connect(limiter)
    this.master = master
    this.pulse = pulseWave(ctx, 0.25)
    this.noise = noiseBuffer(ctx)
    this.nextAt = ctx.currentTime + 0.1
    this.timer = window.setInterval(() => this.schedule(), 25)
  }

  /** toggles mute; returns the new muted state */
  toggleMute(): boolean {
    const { ctx, master } = this
    this.muted = !this.muted
    if (ctx && master) {
      master.gain.cancelScheduledValues(ctx.currentTime)
      master.gain.setValueAtTime(master.gain.value, ctx.currentTime)
      master.gain.linearRampToValueAtTime(this.muted ? 0 : VOLUME, ctx.currentTime + 0.2)
    }
    return this.muted
  }

  stop() {
    const { ctx, master } = this
    window.clearInterval(this.timer)
    if (!ctx || !master) return
    master.gain.cancelScheduledValues(ctx.currentTime)
    master.gain.setValueAtTime(master.gain.value, ctx.currentTime)
    master.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.4)
    setTimeout(() => ctx.close(), 500)
    this.ctx = null
  }

  private schedule() {
    const ctx = this.ctx
    if (!ctx) return
    const total = ROOTS.length * 8
    while (this.nextAt < ctx.currentTime + 0.12) {
      const s = this.step % total
      const t = this.nextAt
      if (s === 0) {
        this.melodyIdx = 0
        this.melodyNextStep = 0
      }
      if (s === this.melodyNextStep && this.melodyIdx < MELODY.length) {
        const [note, len] = MELODY[this.melodyIdx++]
        this.tone(hz(note), t, len * STEP * 0.92, 'lead')
        this.melodyNextStep += len
      }
      const off = BASS_SHAPE[s % 8]
      if (off >= 0) this.tone(hz(ROOTS[Math.floor(s / 8)] + off), t, STEP * 0.9, 'bass')
      if (s % 2 === 1) this.hat(t)
      this.step++
      this.nextAt += STEP
    }
  }

  private tone(f: number, t: number, dur: number, voice: 'lead' | 'bass') {
    const ctx = this.ctx!
    const osc = ctx.createOscillator()
    if (voice === 'lead') osc.setPeriodicWave(this.pulse!)
    else osc.type = 'triangle'
    osc.frequency.setValueAtTime(f, t)
    const g = ctx.createGain()
    const peak = voice === 'lead' ? 0.45 : 0.7
    g.gain.setValueAtTime(0, t)
    g.gain.linearRampToValueAtTime(peak, t + 0.01)
    g.gain.exponentialRampToValueAtTime(peak * 0.4, t + Math.min(dur, 0.3))
    g.gain.linearRampToValueAtTime(0, t + dur)
    osc.connect(g).connect(this.master!)
    osc.start(t)
    osc.stop(t + dur + 0.02)
  }

  private hat(t: number) {
    const ctx = this.ctx!
    const src = ctx.createBufferSource()
    src.buffer = this.noise
    const hp = ctx.createBiquadFilter()
    hp.type = 'highpass'
    hp.frequency.value = 8000
    const g = ctx.createGain()
    g.gain.setValueAtTime(0.12, t)
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.04)
    src.connect(hp).connect(g).connect(this.master!)
    src.start(t)
    src.stop(t + 0.05)
  }
}

/** NES-style pulse with the given duty cycle, as Fourier terms */
function pulseWave(ctx: AudioContext, duty: number): PeriodicWave {
  const n = 64
  const real = new Float32Array(n)
  const imag = new Float32Array(n)
  for (let k = 1; k < n; k++) {
    real[k] = (2 / (k * Math.PI)) * Math.sin(k * Math.PI * duty) * Math.cos(k * Math.PI * duty)
    imag[k] = (2 / (k * Math.PI)) * Math.sin(k * Math.PI * duty) * Math.sin(k * Math.PI * duty)
  }
  return ctx.createPeriodicWave(real, imag)
}

function noiseBuffer(ctx: AudioContext): AudioBuffer {
  const buf = ctx.createBuffer(1, ctx.sampleRate * 0.1, ctx.sampleRate)
  const d = buf.getChannelData(0)
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1
  return buf
}
