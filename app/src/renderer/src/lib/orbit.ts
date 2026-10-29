/** 三点轨道的投影计算：纯函数，组件只负责把结果写进 style。
 *
 *  三个点在一个倾斜的圆盘上等分 120°。盘面坐标 (R·cosθ, R·sinθ) 绕 x 轴
 *  倾斜 tilt，得到深度 z（朝向观察者为正）；透视系数 f / (f − z)，f = 3R，
 *  所以近处的点更大；透明度随深度从 0.3 到 1；z-index 按深度排序，近的盖在远的上面。 */

export interface OrbitShape {
  /** 圆盘半径，px */
  radius: number
  /** 圆盘倾角，弧度 */
  tilt: number
  /** 收拢进度 0..1：半径乘以 (1 − collapse)，1 时三点重合在中心 */
  collapse?: number
}

export interface DotPose {
  x: number
  y: number
  scale: number
  opacity: number
  /** 深度排序用的整数，越大越靠近观察者 */
  z: number
}

export const MIN_OPACITY = 0.3
/** 默认转速，圈/秒 */
export const TURNS_PER_SECOND = 0.45

/** 第 i 个点（共 n 个）在 phase（圈数，可大于 1）时的姿态 */
export function orbitPose(
  phase: number,
  i: number,
  n: number,
  shape: OrbitShape
): DotPose {
  const r = shape.radius * (1 - clamp01(shape.collapse ?? 0))
  const theta = (phase + i / n) * Math.PI * 2
  const flat = r * Math.cos(theta)
  const y3 = r * Math.sin(theta) * Math.cos(shape.tilt)
  const z = r * Math.sin(theta) * Math.sin(shape.tilt)
  const f = 3 * shape.radius
  const k = f / (f - z)
  // 深度归一化到 −1..1；圆盘摆平（tilt = 0）时所有点同深度，取中间值
  const span = shape.radius * Math.sin(shape.tilt)
  const depth = span > 1e-6 ? z / span : 0
  return {
    x: flat * k,
    y: y3 * k,
    scale: k,
    opacity: MIN_OPACITY + (1 - MIN_OPACITY) * (0.5 + 0.5 * depth),
    z: Math.round((z + shape.radius) * 100),
  }
}

/** 默认倾角：14px 用 32°，其余 24° */
export function defaultTilt(size: number): number {
  return ((size <= 14 ? 32 : 24) * Math.PI) / 180
}

/** 28px 及以上的圆盘带 ±9° 的缓慢摆动，14px 关掉 */
export function wobbleTilt(base: number, size: number, tSeconds: number): number {
  if (size < 28) return base
  return base + ((9 * Math.PI) / 180) * Math.sin((tSeconds * Math.PI * 2) / 5)
}

/** 减少动态效果：三点排成一行，只做依次明暗 */
export function stillPose(phase: number, i: number, n: number, gap: number): DotPose {
  const wave = 0.5 + 0.5 * Math.cos((phase - i / n) * Math.PI * 2)
  return {
    x: (i - (n - 1) / 2) * gap,
    y: 0,
    scale: 1,
    opacity: MIN_OPACITY + (1 - MIN_OPACITY) * wave,
    z: 0,
  }
}

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v))
}
