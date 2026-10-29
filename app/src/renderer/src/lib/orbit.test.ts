import { describe, expect, it } from 'vitest'
import {
  MIN_OPACITY,
  defaultTilt,
  orbitPose,
  stillPose,
  wobbleTilt,
} from './orbit'

import type { OrbitShape } from './orbit'
const shape: OrbitShape = { radius: 10, tilt: defaultTilt(28) }
const poses = (phase: number, s: OrbitShape = shape) =>
  [0, 1, 2].map((i) => orbitPose(phase, i, 3, s))

describe('orbitPose', () => {
  it('近处的点更大、更不透明、z 更高', () => {
    const ps = poses(0.1)
    const near = ps.reduce((a, b) => (b.z > a.z ? b : a))
    const far = ps.reduce((a, b) => (b.z < a.z ? b : a))
    expect(near.scale).toBeGreaterThan(far.scale)
    expect(near.opacity).toBeGreaterThan(far.opacity)
    expect(far.opacity).toBeGreaterThanOrEqual(MIN_OPACITY)
    expect(near.opacity).toBeLessThanOrEqual(1)
  })

  it('三点按 120° 等分，转一圈回到原位', () => {
    const a = poses(0.2)
    const b = poses(1.2)
    a.forEach((p, i) => {
      expect(p.x).toBeCloseTo(b[i].x, 9)
      expect(p.y).toBeCloseTo(b[i].y, 9)
    })
    // 三点的盘面坐标之和为重心（透视前），平面内无偏移
    const flat = [0, 1, 2].map((i) => orbitPose(0, i, 3, { radius: 10, tilt: 0 }))
    expect(flat.reduce((s, p) => s + p.x, 0)).toBeCloseTo(0, 6)
  })

  it('收拢到 1 时三点重合在中心', () => {
    for (const p of poses(0.37, { ...shape, collapse: 1 })) {
      expect(p.x).toBeCloseTo(0, 9)
      expect(p.y).toBeCloseTo(0, 9)
      expect(p.scale).toBeCloseTo(1, 9)
    }
  })

  it('收拢是单调的：半径随 collapse 增大而减小', () => {
    const radius = (c: number) => {
      const p = orbitPose(0, 0, 3, { ...shape, collapse: c })
      return Math.hypot(p.x, p.y)
    }
    expect(radius(0.25)).toBeLessThan(radius(0))
    expect(radius(0.75)).toBeLessThan(radius(0.25))
  })

  it('圆盘摆平时没有深度差', () => {
    const ps = poses(0.3, { radius: 10, tilt: 0 })
    expect(new Set(ps.map((p) => p.opacity.toFixed(6))).size).toBe(1)
  })
})

describe('wobbleTilt', () => {
  it('14px 不摆动，28px 在 ±9° 内摆动', () => {
    const base = defaultTilt(28)
    expect(wobbleTilt(defaultTilt(14), 14, 1.3)).toBe(defaultTilt(14))
    const max = (9 * Math.PI) / 180
    for (let t = 0; t < 5; t += 0.25) {
      expect(Math.abs(wobbleTilt(base, 28, t) - base)).toBeLessThanOrEqual(max + 1e-9)
    }
  })
})

describe('stillPose', () => {
  it('排成一行不位移，只改透明度', () => {
    const ps = [0, 1, 2].map((i) => stillPose(0.4, i, 3, 8))
    expect(ps.map((p) => p.y)).toEqual([0, 0, 0])
    expect(ps.map((p) => p.x)).toEqual([-8, 0, 8])
    expect(new Set(ps.map((p) => p.opacity)).size).toBeGreaterThan(1)
  })
})
