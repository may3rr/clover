/** Running-screen progress: per-layer fractions from the backend's
 *  `progress` events, combined into one 0..1 figure. Weights follow how
 *  long each layer usually takes (support and authenticity dominate). */

export type RunStatus = 'waiting' | 'running' | 'done' | 'failed'

export interface LayerProgress {
  status: RunStatus
  /** latest backend fraction for a running layer, 0..1 */
  frac?: number
}

export const LAYER_WEIGHT: Record<string, number> = {
  authenticity: 0.3,
  support: 0.35,
  norms: 0.15,
  distribution: 0.1,
  overview: 0.1,
}

/** Fraction a layer contributes: finished (done or failed) counts as 1,
 *  waiting as 0; a running layer reports its backend fraction. */
export function layerFrac(p: LayerProgress | undefined): number {
  if (!p) return 0
  if (p.status === 'done' || p.status === 'failed') return 1
  if (p.status === 'waiting') return 0
  return Math.min(Math.max(p.frac ?? 0, 0), 1)
}

/** Weighted overall progress over the layers present in `layers`. Kept
 *  below 1 until `finished` — the last step (report assembly) is only
 *  done when the backend says so. */
export function overallProgress(
  layers: Record<string, LayerProgress>,
  finished: boolean
): number {
  if (finished) return 1
  let sum = 0
  let weight = 0
  for (const [key, p] of Object.entries(layers)) {
    const w = LAYER_WEIGHT[key] ?? 0.1
    sum += w * layerFrac(p)
    weight += w
  }
  if (!weight) return 0
  return Math.min(sum / weight, 0.99)
}
