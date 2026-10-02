"""End-to-end smoke: T4b distribution + T5 lint on docx fixtures.

    python scripts/smoke_t45.py [docx ...]

Defaults to tests/fixtures/numeric_en.docx and numeric_unordered_en.docx.
Runs the real `function`/`typo` LLM tasks and the committed benchmark
JSON. Prints findings by layer/severity, revision counts by kind, the
benchmark summary, token usage and approximate cost.
"""

import asyncio
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citecheck.distribution.bench import load_benchmark
from citecheck.distribution.layer import run_distribution
from citecheck.lint.norms import check_norms
from citecheck.lint.reorder import plan_reorder
from citecheck.lint.typos import check_typos
from citecheck.llm.client import stats_scope
from citecheck.parse import parse_docx

# 元 / M tokens (input, output) — reporting only
PRICES = {
    "qwen3.8-flash": (0.8, 2.7),
    "qwen3.7-flash": (0.2, 0.8),
    "qwen3.8-max": (12.0, 36.0),
    "qwen3.7-max": (12.0, 36.0),
}


def bench_summary(bench: dict) -> None:
    print(f"\n== 基准 {bench['id']} ({bench['name']}): n_papers="
          f"{bench['n_papers']}, built_at={bench['built_at']}")
    print("  canonical   share.mean  share.med   [q1,q3]        "
          "density med  [q1,q3]      present")
    for canon, s in bench["sections"].items():
        sh, de = s["share"], s["density_per_1k_words"]
        print(f"  {canon:11s} {sh['mean']:8.3f}   {sh['median']:8.3f}   "
              f"[{sh['q1']:.3f},{sh['q3']:.3f}]  {de['median']:8.2f}   "
              f"[{de['q1']:.2f},{de['q3']:.2f}]  {s['present_in']}")
    sr = bench["sentence_refs"]
    for k in ("share_ge2", "share_ge3", "share_ge5"):
        s = sr[k]
        print(f"  {k:11s} median={s['median']:.3f} "
              f"[{s['q1']:.3f},{s['q3']:.3f}]")


async def run_doc(path: Path, stats) -> None:
    parsed = parse_docx(path)
    print(f"\n===== {path.name}: {len(parsed.paragraphs)} paragraphs, "
          f"{len(parsed.markers)} markers, {len(parsed.references)} refs, "
          f"style={parsed.document.citation_style}, "
          f"managed_by={parsed.document.managed_by}")

    findings = []
    dist, dist_findings = await run_distribution(parsed)
    findings += dist_findings
    norm_findings = check_norms(parsed)
    findings += norm_findings
    typo_findings, typo_revs = await check_typos(parsed)
    findings += typo_findings
    reorder_revs = plan_reorder(parsed)

    print("\n  -- 分布 (distribution)")
    if dist.note:
        print(f"  note: {dist.note}")
    for s in dist.sections:
        print(f"  {s.canonical:11s} words={s.words:5d} cites={s.citations:3d} "
              f"share={s.share:.3f}({s.share_flag}) "
              f"density={s.density:6.1f}({s.density_flag})")
    sr = dist.sentence_refs
    print(f"  sentence_refs: ge2={sr.share_ge2:.2f} ge3={sr.share_ge3:.2f} "
          f"ge5={sr.share_ge5:.2f}")
    if dist.functions is not None:
        print(f"  functions: {dist.functions}")

    print("\n  -- findings by layer/severity")
    by_ls = Counter((f.layer, f.severity) for f in findings)
    for (layer, sev), n in sorted(by_ls.items()):
        print(f"  {layer:13s} {sev:6s} {n}")
    for f in findings:
        print(f"    [{f.layer}/{f.severity}] {f.title}"
              + (f"  @ {f.anchor.paragraph_id}:{f.anchor.start}-"
                 f"{f.anchor.end}" if f.anchor else ""))

    revs = typo_revs + reorder_revs
    print("\n  -- revisions by kind")
    for kind, n in sorted(Counter(r.kind for r in revs).items()):
        print(f"  {kind:16s} {n}")
    for r in reorder_revs:
        if r.move_after is not None:
            print(f"    move {r.anchor.paragraph_id} -> after {r.move_after} "
                  f"({r.old[:30]!r} -> {r.new[:30]!r})")
    for r in typo_revs[:10]:
        print(f"    typo @ {r.anchor.paragraph_id}:{r.anchor.start}-"
              f"{r.anchor.end} {r.old!r} -> {r.new!r} ({r.reason})")


async def main() -> None:
    base = Path(__file__).parent.parent / "tests/fixtures"
    paths = [Path(a) for a in sys.argv[1:]] or [
        base / "numeric_en.docx", base / "numeric_unordered_en.docx"]
    t0 = time.monotonic()

    bench = load_benchmark()
    bench_summary(bench)

    with stats_scope() as stats:
        for p in paths:
            await run_doc(p, stats)

    print(f"\n== LLM calls: local={stats.local} cloud={stats.cloud}")
    total = 0.0
    if stats.usage:
        print("  tokens (uncached calls):")
        for model, u in sorted(stats.usage.items()):
            pin, pout = PRICES.get(model, (0.0, 0.0))
            cost = (u["prompt"] * pin + u["completion"] * pout) / 1e6
            total += cost
            print(f"    {model}: in={u['prompt']} out={u['completion']} "
                  f"≈{cost:.4f} 元")
        print(f"  ≈ total cost: {total:.4f} 元")
    print(f"  wall time: {time.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
