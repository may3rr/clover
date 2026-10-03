import { describe, it, expect } from 'vitest'
import { validateClips, sampleState, sampleAction, STATES } from './mascot'

describe('mascot clips', () => {
  it('states loop and actions start and end at rest', () => {
    expect(validateClips()).toEqual([])
  })

  it('state loops are seamless at the period boundary', () => {
    for (const name of Object.keys(STATES) as (keyof typeof STATES)[]) {
      const a: Record<string, number> = {}
      const b: Record<string, number> = {}
      sampleState(name, 0, a, 1)
      sampleState(name, STATES[name].dur - 1e-6, b, 1)
      for (const ch of Object.keys(a)) expect(b[ch]).toBeCloseTo(a[ch], 3)
    }
  })

  it('an action is a no-op once finished', () => {
    const p: Record<string, number> = {}
    sampleAction('nod', 5, p, 1)
    expect(p).toEqual({})
  })
})
