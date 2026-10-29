import { describe, expect, it } from 'vitest'
import { migrateVenue } from './targetVenue'

describe('target venue', () => {
  it('turns the old menu ids into names', () => {
    expect(migrateVenue('emnlp')).toBe('EMNLP')
    expect(migrateVenue('findings-emnlp')).toBe('Findings of EMNLP')
    expect(migrateVenue('acl')).toBe('ACL')
  })

  it('keeps typed names and blank', () => {
    expect(migrateVenue(' 计算机学报 ')).toBe('计算机学报')
    expect(migrateVenue('')).toBe('')
    // nothing stored: no benchmarking until the user types a venue
    expect(migrateVenue(null)).toBe('')
  })
})
