import type { Claim, Report, SupportCheck } from '../types/report'
import type { ListItem } from './items'

export interface SupportDetail {
  claim: Claim | null
  check: SupportCheck | null
  /** the sentence the claim was judged in */
  sentence: string | null
  sourceTitle: string | null
  excerpt: string | null
  evidenceSpan: [number, number] | null
  label: string | null
  sourceKind: string | null
  rationale: string | null
}

/** Resolve a support-layer finding to its claim + support_check.
 * Path: finding.refs[0] is the ref_id; the claim is the one in the
 * finding's paragraph whose marker_ids include a marker pointing at
 * that ref; the check pairs (claim_id, ref_id). */
export function supportForFinding(
  report: Report,
  item: ListItem
): SupportDetail {
  const empty: SupportDetail = {
    claim: null,
    check: null,
    sentence: null,
    sourceTitle: null,
    excerpt: null,
    evidenceSpan: null,
    label: null,
    sourceKind: null,
    rationale: null,
  }
  const f = item.finding
  if (!f) return empty
  const refId = f.refs?.[0]
  const pid = f.anchor?.paragraph_id
  const claims = report.claims ?? []
  const checks = report.support_checks ?? []
  const markers = report.markers ?? []

  const claimsInPara = pid
    ? claims.filter((c) => c.paragraph_id === pid)
    : claims
  const markerRefs = (c: Claim): Set<string> =>
    new Set(
      (c.marker_ids ?? [])
        .map((mid) => markers.find((m) => m.id === mid)?.ref_ids ?? [])
        .flat()
    )
  // one paragraph can hold several claims citing the same ref — the
  // finding's anchor span picks the right one
  const a = f.anchor
  const overlaps = (c: Claim) =>
    !!a && c.paragraph_id === a.paragraph_id && c.start < a.end && a.start < c.end
  const claim =
    claimsInPara.find((c) => overlaps(c) && (!refId || markerRefs(c).has(refId))) ??
    claimsInPara.find(overlaps) ??
    claimsInPara.find((c) => refId && markerRefs(c).has(refId)) ??
    claimsInPara[0] ??
    null
  const check =
    checks.find(
      (c) => c.claim_id === claim?.id && (!refId || c.ref_id === refId)
    ) ??
    checks.find((c) => c.claim_id === claim?.id) ??
    checks.find((c) => refId && c.ref_id === refId) ??
    null
  return {
    claim,
    check,
    sentence: claim?.sentence ?? null,
    sourceTitle: check?.source_title ?? null,
    excerpt: check?.source_excerpt ?? null,
    evidenceSpan: (check?.evidence_span as [number, number] | undefined) ?? null,
    label: check?.label ?? null,
    sourceKind: check?.source_kind ?? null,
    rationale: check?.rationale ?? null,
  }
}
