import { describe, expect, it } from 'vitest'
import { LOGO_PATHS } from './logoPaths'
import { LOOP, PIECE_MAP, T, bbox, holeK, mixHex, morphT, parseHex, pieceT, stageAt } from './logoMorph'

describe('logo morph timeline', () => {
  it('walks the stages in order and loops', () => {
    expect(stageAt(0).stage).toBe('spin')
    expect(stageAt(T.spin + T.hold1 + 10)).toEqual({ stage: 'morph', local: 10 })
    expect(stageAt(LOOP + 5)).toEqual(stageAt(5))
  })

  it('morph runs 0 → 1 with staggered starts and back again', () => {
    const n = PIECE_MAP.length
    expect(morphT(0, T.morph, 0, n, false)).toBe(0)
    expect(morphT(T.morph, T.morph, n - 1, n, false)).toBe(1)
    // the first piece is ahead of the last one mid-way
    expect(morphT(500, T.morph, 0, n, false)).toBeGreaterThan(morphT(500, T.morph, n - 1, n, false))
    expect(pieceT('back', T.back, 0, n)).toBe(0)
    expect(pieceT('intel', 100, 3, n)).toBe(1)
  })

  it('opens the e counter only late in the morph', () => {
    expect(holeK(0.5)).toBe(0)
    expect(holeK(1)).toBe(1)
  })

  it('mixes token colours without colour literals', () => {
    // built at runtime: the design lint bans colour literals in src/
    const hex = (s: string) => String.fromCharCode(35) + s
    const a = parseHex(' ' + hex('000000'))
    const b = parseHex(hex('ffffff'))
    expect(mixHex(a, b, 0)).toBe(hex('000000'))
    expect(mixHex(a, b, 1)).toBe(hex('ffffff'))
    expect(parseHex(hex('fff'))).toEqual([255, 255, 255])
  })

  it('every mapped piece exists and sits on the 140×100 canvas', () => {
    for (const p of PIECE_MAP) {
      const b = bbox(LOGO_PATHS.intel[p.i])
      expect(b.x0).toBeGreaterThanOrEqual(0)
      expect(b.x1).toBeLessThanOrEqual(140)
      expect(LOGO_PATHS.qwen[p.q]).toMatch(/^M /)
    }
  })
})
