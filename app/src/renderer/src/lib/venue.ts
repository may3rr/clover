import type { Distribution, ExemplarInfo, ExemplarValue, VenueMetric } from '../types/report'

export const GROUP_LABEL: Record<string, string> = {
  structure: '章节结构',
  distribution: '引用位置',
  references: '参考文献构成',
  functions: '引用功能构成',
  elements: '研究要素',
  length: '篇幅与图表',
}

/** "44%" / "51 条" / "2.0 年" / "有" — one value of a measure. */
export function fmtMetric(m: Pick<VenueMetric, 'unit' | 'kind'>, v: number | null | undefined): string {
  if (v === null || v === undefined) return '未知'
  if (m.kind === 'bool') return v ? '有' : '没有'
  if (m.unit === '%') return `${(v * 100).toFixed(0)}%`
  const n = m.unit === '次' || m.unit === '年' ? v.toFixed(1) : v.toFixed(0)
  return m.unit ? `${n} ${m.unit}` : n
}

/** The measures a finding names, in its order (unknown keys dropped). */
export function metricsFor(d: Distribution | null | undefined, keys: string[]): VenueMetric[] {
  const byKey = new Map((d?.venue_metrics ?? []).map((m) => [m.key, m]))
  return keys.map((k) => byKey.get(k)).filter((m): m is VenueMetric => !!m)
}

/** Exemplar rows for one measure: the topic-closest papers first, then
 *  by value, high to low; unknown values last. */
export function exemplarRows(
  m: VenueMetric,
  infos: ExemplarInfo[]
): { value: ExemplarValue; info: ExemplarInfo | undefined }[] {
  const byId = new Map(infos.map((e) => [e.doc_id, e]))
  return (m.exemplars ?? [])
    .map((value) => ({ value, info: byId.get(value.doc_id) }))
    .sort(
      (a, b) =>
        Number(!!b.info?.similar) - Number(!!a.info?.similar) ||
        (b.value.value ?? -Infinity) - (a.value.value ?? -Infinity)
    )
}

/** "本文没有，范文中 68% 有" for a yes/no measure. */
export function boolSummary(m: VenueMetric): string {
  const mine = m.value === null || m.value === undefined ? '无法判断' : m.value ? '有' : '没有'
  const rate = m.rate === null || m.rate === undefined ? '' : `，范文中 ${(m.rate * 100).toFixed(0)}% 有`
  return `本文${mine}${rate}`
}

/** Every measure grouped for the "全部对标指标" view. */
export function groupedMetrics(d: Distribution | null | undefined): [string, VenueMetric[]][] {
  const out = new Map<string, VenueMetric[]>()
  for (const m of d?.venue_metrics ?? []) {
    const g = m.group ?? 'length'
    out.set(g, [...(out.get(g) ?? []), m])
  }
  return Object.keys(GROUP_LABEL)
    .filter((g) => out.has(g))
    .map((g) => [g, out.get(g)!])
}
