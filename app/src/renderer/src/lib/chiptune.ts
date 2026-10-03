/** 8-bit rendering of Debussy's "Clair de lune" opening (public domain;
 * score data in clairDeLune.ts) for the credits easter egg, synthesized
 * live with WebAudio: 25% pulse melody, 12.5% pulse for the third below,
 * triangle bass. No drums — it should stay as quiet as moonlight, fine to
 * open in a lecture hall. */

import { CLAIR, CLAIR_SPAN } from './clairDeLune'

/** seconds per sixteenth — a touch quicker than the score's ♩ = 60 */
const SIXTEENTH = 0.22

/** master level: audible, never loud */
const VOLUME = 0.035

const hz = (m: number) => 440 * Math.pow(2, (m - 69) / 12)

export class Chiptune {
  private ctx: AudioContext | null = null
  private master: GainNode | null = null
  private lead: PeriodicWave | null = null
  private inner: PeriodicWave | null = null
  private timer = 0
  private loopAt = 0 // audio time the current pass of the piece began
  private idx = 0 // next event to schedule
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
    this.lead = pulseWave(ctx, 0.25)
    this.inner = pulseWave(ctx, 0.125)
    this.loopAt = ctx.currentTime + 0.3
    this.idx = 0
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
    const horizon = ctx.currentTime + 0.25
    for (;;) {
      if (this.idx >= CLAIR.length) {
        // loop with a breath of silence after the phrase resolves
        this.loopAt += (CLAIR_SPAN + 8) * SIXTEENTH
        this.idx = 0
      }
      const [on, len, note, voice] = CLAIR[this.idx]
      const t = this.loopAt + on * SIXTEENTH
      if (t > horizon) break
      if (t >= ctx.currentTime - 0.01) this.tone(hz(note), t, len * SIXTEENTH, voice)
      this.idx++
    }
  }

  private tone(f: number, t: number, dur: number, voice: number) {
    const ctx = this.ctx!
    const osc = ctx.createOscillator()
    if (voice === 0) osc.setPeriodicWave(this.lead!)
    else if (voice === 1) osc.setPeriodicWave(this.inner!)
    else osc.type = 'triangle'
    osc.frequency.setValueAtTime(f, t)
    if (voice === 0 && dur > 0.6) {
      // a slow vibrato on held melody notes, like a soft NES lead
      const lfo = ctx.createOscillator()
      const depth = ctx.createGain()
      lfo.frequency.value = 5
      depth.gain.setValueAtTime(0, t)
      depth.gain.linearRampToValueAtTime(f * 0.006, t + 0.4)
      lfo.connect(depth).connect(osc.frequency)
      lfo.start(t)
      lfo.stop(t + dur + 0.05)
    }
    const g = ctx.createGain()
    const peak = [0.45, 0.22, 0.6][voice] ?? 0.3
    g.gain.setValueAtTime(0, t)
    g.gain.linearRampToValueAtTime(peak, t + 0.02)
    g.gain.exponentialRampToValueAtTime(peak * 0.45, t + Math.min(dur, 0.5))
    g.gain.linearRampToValueAtTime(0, t + dur)
    osc.connect(g).connect(this.master!)
    osc.start(t)
    osc.stop(t + dur + 0.05)
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
