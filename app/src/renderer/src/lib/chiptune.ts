/** A tiny 8-bit loop for the credits easter egg, synthesized live with
 * WebAudio — 25% pulse lead, triangle bass, noise hats. Original tune on
 * a I–vi–IV–V progression; no audio files shipped. */

const BPM = 138
const STEP = 60 / BPM / 2 // eighth notes
const _ = -1 // rest

// lead, MIDI note numbers (C5 = 72), 8 eighths per bar
const LEAD = [
  72, 76, 79, 76, 84, _, 79, 76,
  76, 72, 69, 72, 76, _, 79, 81,
  77, 81, 84, 81, 77, _, 76, 74,
  74, _, 79, _, 74, 76, 77, 79,
  84, _, 83, 81, 79, _, 76, 79,
  81, _, 79, 76, 72, _, 74, 76,
  77, 76, 74, 72, 74, _, 77, 79,
  76, _, 74, _, 72, _, _, _,
]
const ROOTS = [48, 45, 41, 43, 48, 45, 41, 43] // C Am F G, twice
const BASS_SHAPE = [0, _, 12, _, 0, _, 12, 7]

const hz = (m: number) => 440 * Math.pow(2, (m - 69) / 12)

export class Chiptune {
  private ctx: AudioContext | null = null
  private master: GainNode | null = null
  private pulse: PeriodicWave | null = null
  private noise: AudioBuffer | null = null
  private timer = 0
  private step = 0
  private nextAt = 0

  start() {
    const ctx = new AudioContext()
    this.ctx = ctx
    const master = ctx.createGain()
    master.gain.setValueAtTime(0, ctx.currentTime)
    master.gain.linearRampToValueAtTime(0.09, ctx.currentTime + 0.6)
    master.connect(ctx.destination)
    this.master = master
    this.pulse = pulseWave(ctx, 0.25)
    this.noise = noiseBuffer(ctx)
    this.step = 0
    this.nextAt = ctx.currentTime + 0.1
    this.timer = window.setInterval(() => this.schedule(), 25)
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
    while (this.nextAt < ctx.currentTime + 0.12) {
      const i = this.step % LEAD.length
      const t = this.nextAt
      if (LEAD[i] !== _) this.tone(hz(LEAD[i]), t, STEP * 0.9, 'lead')
      const off = BASS_SHAPE[i % 8]
      if (off !== _) this.tone(hz(ROOTS[Math.floor(i / 8)] + off), t, STEP * 0.95, 'bass')
      if (i % 2 === 1) this.hat(t)
      if (i % 4 === 0) this.kick(t)
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
    const peak = voice === 'lead' ? 0.5 : 0.8
    g.gain.setValueAtTime(peak, t)
    g.gain.exponentialRampToValueAtTime(peak * 0.35, t + dur * 0.6)
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
    hp.frequency.value = 7000
    const g = ctx.createGain()
    g.gain.setValueAtTime(0.25, t)
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.05)
    src.connect(hp).connect(g).connect(this.master!)
    src.start(t)
    src.stop(t + 0.06)
  }

  private kick(t: number) {
    const ctx = this.ctx!
    const osc = ctx.createOscillator()
    osc.type = 'triangle'
    osc.frequency.setValueAtTime(150, t)
    osc.frequency.exponentialRampToValueAtTime(45, t + 0.12)
    const g = ctx.createGain()
    g.gain.setValueAtTime(0.9, t)
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.14)
    osc.connect(g).connect(this.master!)
    osc.start(t)
    osc.stop(t + 0.15)
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
