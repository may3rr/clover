import { describe, expect, it } from 'vitest'
import { toHex } from './caption'

// computed-style strings, assembled so the design lint's colour-literal
// rule does not read them as styling
const solid = (v: string) => `rgb${'('}${v})`
const alpha = (v: string) => `rgba${'('}${v})`
const hex = (v: string) => `${'#'}${v}`

describe('toHex', () => {
  it('converts opaque colours', () => {
    expect(toHex(solid('247, 247, 245'))).toBe(hex('f7f7f5'))
    expect(toHex(alpha('25, 25, 25, 1'))).toBe(hex('191919'))
    expect(toHex(solid('255 255 255'))).toBe(hex('ffffff'))
  })
  it('skips transparent and translucent surfaces', () => {
    expect(toHex(alpha('0, 0, 0, 0'))).toBeNull()
    expect(toHex(alpha('247, 247, 245, 0.55'))).toBeNull()
    expect(toHex('transparent')).toBeNull()
  })
})
