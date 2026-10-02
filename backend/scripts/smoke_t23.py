"""End-to-end smoke: parse fixture -> T2 verification -> T3 support.

    python scripts/smoke_t23.py [docx]

Defaults to tests/fixtures/numeric_en.docx. Uses real APIs, the real
sqlite cache, and the real LLM router (extract prefers local mlx).
"""

import asyncio
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citecheck.llm.client import stats_scope
from citecheck.parse import parse_docx
from citecheck.refs.sources import RetrievalClient
from citecheck.refs.verify import verify_references
from citecheck.support.layer import run_support


async def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                Path(__file__).parent.parent / "tests/fixtures/numeric_en.docx")
    t0 = time.monotonic()

    parsed = parse_docx(path)
    print(f"== {path.name}: {len(parsed.paragraphs)} paragraphs, "
          f"{len(parsed.markers)} markers, {len(parsed.references)} references")

    with stats_scope() as stats:
        async with RetrievalClient() as client:
            checks, auth_findings = await verify_references(
                parsed.references, parsed.paragraphs, client
            )
            claims, support_checks, sup_findings = await run_support(
                parsed, checks
            )

    counts = Counter(c.status for c in checks)
    print("\n== T2 真实性核验")
    for c, r in zip(checks, parsed.references):
        line = f"  {r.id} [{c.status:12s}] {(r.title or r.raw)[:70]}"
        if c.issues:
            line += f"  — {'; '.join(c.issues)[:80]}"
        print(line)
    print("  status:", dict(counts))

    label_counts = Counter(s.label for s in support_checks)
    print("\n== T3 支持度")
    print(f"  claims: {len(claims)}   support_checks: {len(support_checks)}")
    print("  labels:", dict(label_counts))

    def reason_of(s) -> str:
        if s.label != "undetermined":
            return "-"
        r = s.rationale or ""
        if "未能获取" in r:
            return "no source"
        if "未能在原文中定位" in r:
            return "evidence not located"
        if "未给出原文证据" in r:
            return "no evidence"
        if "输出无效" in r:
            return "model invalid"
        return "model undetermined"

    breakdown = Counter(
        (s.label, s.source_kind, reason_of(s)) for s in support_checks
    )
    print("  label        kind       reason                 count")
    for (label, kind, reason), n in sorted(breakdown.items()):
        print(f"  {label:12s} {kind:9s} {reason:22s} {n}")

    claim_by_id = {c.id: c for c in claims}
    title_by_ref = {
        r.id: (c.matched or {}).get("title") or (r.title or r.raw)
        for r, c in zip(parsed.references, checks)
    }
    print("\n  undetermined with a source:")
    for s in support_checks:
        if s.label != "undetermined" or s.source_kind == "none":
            continue
        cl = claim_by_id.get(s.claim_id)
        print(f"    c={s.claim_id} r={s.ref_id} kind={s.source_kind} "
              f"claim={(cl.text if cl else '')[:80]!r} "
              f"ref={str(title_by_ref.get(s.ref_id))[:50]!r} "
              f"why={s.rationale[:60]!r}")

    for s in support_checks:
        if s.label != "undetermined":
            print(f"  [{s.label:12s}] claim={s.claim_id} ref={s.ref_id} "
                  f"kind={s.source_kind} ev={str(s.evidence)[:60]!r}")

    print(f"\n  authenticity findings: {len(auth_findings)}   "
          f"support findings: {len(sup_findings)}")
    print(f"  LLM calls: local={stats.local} cloud={stats.cloud}")
    # 元 / M tokens (input, output)
    prices = {
        "qwen3.8-flash": (0.8, 2.7),
        "qwen3.7-flash": (0.2, 0.8),
        "qwen3.8-max": (12.0, 36.0),
        "qwen3.7-max": (12.0, 36.0),
    }
    total_cost = 0.0
    if stats.usage:
        print("  tokens (uncached calls):")
        for model, u in sorted(stats.usage.items()):
            pin, pout = prices.get(model, (0.0, 0.0))
            cost = (u["prompt"] * pin + u["completion"] * pout) / 1e6
            total_cost += cost
            print(f"    {model}: in={u['prompt']} out={u['completion']} "
                  f"≈{cost:.4f} 元")
        print(f"  ≈ total cost: {total_cost:.4f} 元")
    print(f"  wall time: {time.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
