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
    for s in support_checks[:6]:
        print(f"  [{s.label:12s}] claim={s.claim_id} ref={s.ref_id} "
              f"kind={s.source_kind} ev={str(s.evidence)[:60]!r}")
    print(f"\n  authenticity findings: {len(auth_findings)}   "
          f"support findings: {len(sup_findings)}")
    print(f"  LLM calls: local={stats.local} cloud={stats.cloud}")
    print(f"  wall time: {time.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
