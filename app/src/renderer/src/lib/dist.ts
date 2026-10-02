import type { SectionDist } from '../types/report'

export interface BarGeom {
  /** 0..1 fraction for the "本文" fill */
  valueFrac: number
  /** 0..1 band edges + median tick for the "领域常见范围" track */
  q1: number
  q3: number
  median: number
  max: number
}

/** Scale a section's share/density + benchmark IQR onto a 0..1 axis.
 * max = max(value, q3) * 1.15 so both rows share one axis. */
export function barGeom(
  value: number,
  bench: { q1?: number | null; q3?: number | null; median?: number | null } | null
): BarGeom {
  const q1 = bench?.q1 ?? 0
  const q3 = bench?.q3 ?? 0
  const median = bench?.median ?? 0
  const max = Math.max(value, q3, median, 0.0001) * 1.15
  return {
    valueFrac: clamp01(value / max),
    q1: clamp01(q1 / max),
    q3: clamp01(q3 / max),
    median: clamp01(median / max),
    max,
  }
}

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x))
}

/** Sections worth showing in the distribution detail: compared ones
 * (have benchmark stats) that were flagged. */
export function comparedSections(d: {
  sections?: SectionDist[] | null
}): SectionDist[] {
  return (d.sections ?? []).filter(
    (s) =>
      s.bench_share &&
      ((s.share_flag && s.share_flag !== 'within' && s.share_flag !== 'na') ||
        (s.density_flag &&
          s.density_flag !== 'within' &&
          s.density_flag !== 'na'))
  )
}
