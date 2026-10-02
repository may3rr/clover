"""Record arXiv (and fresh Crossref) responses for tests/test_refs.py.

Run once with network access:
    python tests/fixtures/record_arxiv.py

Merges new cache-keyed entries into tests/fixtures/http/refs_cases.json,
same_title_cases.json and arxiv_rescue_cases.json so the verify tests run
fully offline. OpenAlex/S2 entries are intentionally NOT recorded — the
regression scenario for r1/r3/r7 needs those sources "unavailable" (their
keys stay absent, so the offline transport yields ok=False).
"""

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from citecheck.cache import Cache  # noqa: E402
from citecheck.refs.sources import RetrievalClient  # noqa: E402
from citecheck.refs.structure import parse_reference  # noqa: E402

OUT = Path(__file__).parent / "http"

# raw refs exactly as tests/fixtures/record_http.py CASES plus the three
# same-title regression refs (r1 Vaswani, r3 Brown, r7 Mikolov)
CASES = {
    "vaswani": "[1] Vaswani A, Shazeer N, Parmar N, et al. Attention is all "
    "you need. Advances in Neural Information Processing Systems. "
    "2017;30:5998-6008.",
    "devlin": "[2] Devlin J, Chang M-W, Lee K, Toutanova K. BERT: "
    "Pre-training of deep bidirectional transformers for language "
    "understanding. Proceedings of NAACL-HLT. 2019:4171-4186. "
    "doi:10.18653/v1/N19-1423.",
    "lewis": "[4] Lewis P, Perez E, Piktus A, et al. Retrieval-augmented "
    "generation for knowledge-intensive NLP tasks. Advances in Neural "
    "Information Processing Systems. 2020;33:9459-9474.",
    "he_wrong_year": "[6] He K, Zhang X, Ren S, Sun J. Deep residual "
    "learning for image recognition. Proceedings of the IEEE Conference on "
    "Computer Vision and Pattern Recognition. 2018:770-778.",
    "fabricated": "[9] Zhang W, Li Q. Quantum entanglement transformers for "
    "citation verification in low-resource manuscripts. Journal of "
    "Fictional Computation. 2023;99(1):1-25.",
    "zh_ref": "[1] 刘知远, 孙茂松, 林衍凯, 等. 知识表示学习研究进展[J]. "
    "计算机研究与发展, 2016, 53(2): 247-261.",
    "doi_elsewhere": "[1] Vaswani A, Shazeer N, Parmar N, et al. Attention "
    "is all you need. NeurIPS. 2017. doi:10.18653/v1/N19-1423.",
    "brown": "[3] Brown TB, Mann B, Ryder N, et al. Language models are "
    "few-shot learners. Advances in Neural Information Processing "
    "Systems. 2020;33:1877-1901.",
    "mikolov": "[7] Mikolov T, Sutskever I, Chen K, Corrado G, Dean J. "
    "Efficient estimation of word representations in vector space. "
    "International Conference on Learning Representations. 2013.",
}

# which fixture file each case merges into
TARGET = {
    "vaswani": "refs_cases.json",
    "devlin": "refs_cases.json",
    "lewis": "refs_cases.json",
    "he_wrong_year": "refs_cases.json",
    "fabricated": "refs_cases.json",
    "zh_ref": "refs_cases.json",
    "doi_elsewhere": "refs_cases.json",
    "brown": "same_title_cases.json",
    "mikolov": "arxiv_rescue_cases.json",
}
# vaswani/brown are also needed in arxiv_rescue (r1/r3 regression)
EXTRA = {"vaswani": "arxiv_rescue_cases.json", "brown": "arxiv_rescue_cases.json"}


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "rec.sqlite"
    cache = Cache(db)
    new_keys: dict[str, set[str]] = {}
    async with RetrievalClient(cache=cache) as client:
        for name, raw in CASES.items():
            info = parse_reference(raw)
            title = info["title"] or raw[:200]
            surname = info["authors"][0].split()[0] if info["authors"] else ""
            print(f"{name}: title={title[:50]!r} surname={surname!r}")
            r = await client.arxiv_search(title)
            print(f"  arxiv: ok={r.ok} hits={len(r.data or [])}")
            if surname:
                r2 = await client.arxiv_search(title, author=surname)
                print(f"  arxiv+au: ok={r2.ok} hits={len(r2.data or [])}")
            # fresh crossref title searches for the rescue cases (the same-
            # title different-work record must be in the recorded pool)
            if name in ("vaswani", "brown", "mikolov"):
                r3 = await client.crossref_search(title)
                n = len(r3.data or []) if r3.ok else -1
                print(f"  crossref: ok={r3.ok} hits={n}")
                if info["year"]:
                    await client.crossref_search(title, year=info["year"])
            targets = {TARGET[name]}
            if name in EXTRA:
                targets.add(EXTRA[name])
            for t in targets:
                new_keys.setdefault(t, set())
        # figure out which new keys belong to which target file:
        # crossref+arxiv keys recorded while handling each case are tagged
    # simpler: dump everything recorded, then split by which titles each
    # file needs — but keys are opaque hashes. Track per-case keys instead.
    print("(recorded into", db, ")")
    conn = sqlite3.connect(db)
    all_new = {k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM kv")}
    print(f"{len(all_new)} total recorded entries")
    return all_new


async def record() -> dict[str, dict]:
    """Record per case so entries land in the right fixture file."""
    per_file: dict[str, dict] = {}
    tmp = Path(tempfile.mkdtemp())
    for name, raw in CASES.items():
        db = tmp / f"{name}.sqlite"
        cache = Cache(db)
        async with RetrievalClient(cache=cache) as client:
            info = parse_reference(raw)
            title = info["title"] or raw[:200]
            surname = info["authors"][0].split()[0] if info["authors"] else ""
            r = await client.arxiv_search(title)
            print(f"{name}: arxiv ok={r.ok} hits={len(r.data or [])}")
            if surname:
                await client.arxiv_search(title, author=surname)
            if name in ("vaswani", "brown", "mikolov"):
                await client.crossref_search(title)
                if info["year"]:
                    await client.crossref_search(title, year=info["year"])
        conn = sqlite3.connect(db)
        entries = {k: json.loads(v)
                   for k, v in conn.execute("SELECT key, value FROM kv")}
        targets = {TARGET[name]}
        if name in EXTRA:
            targets.add(EXTRA[name])
        for t in targets:
            per_file.setdefault(t, {}).update(entries)
    return per_file


def merge() -> None:
    per_file = asyncio.run(record())
    for fname, entries in per_file.items():
        p = OUT / fname
        data = json.loads(p.read_text()) if p.exists() else {}
        data.update(entries)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                     encoding="utf-8")
        print(f"{fname}: {len(entries)} new, {len(data)} total")


if __name__ == "__main__":
    merge()
