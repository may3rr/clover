"""Record real Crossref/OpenAlex/S2 responses for tests/test_refs.py.

Run once with network access:
    python tests/fixtures/record_http.py
Writes tests/fixtures/http/refs_cases.json mapping cache keys to raw
response bodies; tests seed a Cache with them and never hit the network.
"""

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path

from citecheck.cache import Cache, make_key
from citecheck.refs.sources import RetrievalClient
from citecheck.refs.structure import parse_reference

HERE = Path(__file__).parent
OUT = HERE / "http" / "refs_cases.json"

# (case name, raw reference string)
CASES = {
    # real refs -> verified
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
    # real paper, wrong year (2018 vs 2016) -> mismatch
    "he_wrong_year": "[6] He K, Zhang X, Ren S, Sun J. Deep residual "
    "learning for image recognition. Proceedings of the IEEE Conference on "
    "Computer Vision and Pattern Recognition. 2018:770-778.",
    # fabricated but plausible -> not_found
    "fabricated": "[9] Zhang W, Li Q. Quantum entanglement transformers for "
    "citation verification in low-resource manuscripts. Journal of "
    "Fictional Computation. 2023;99(1):1-25.",
    # real Chinese journal article -> verified or unverifiable
    "zh_ref": "[1] 刘知远, 孙茂松, 林衍凯, 等. 知识表示学习研究进展[J]. "
    "计算机研究与发展, 2016, 53(2): 247-261.",
    # real title, DOI points at a different work -> mismatch
    "doi_elsewhere": "[1] Vaswani A, Shazeer N, Parmar N, et al. Attention "
    "is all you need. NeurIPS. 2017. doi:10.18653/v1/N19-1423.",
}


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    cache = Cache(tmp / "rec.sqlite")
    async with RetrievalClient(cache=cache) as client:
        for name, raw in CASES.items():
            info = parse_reference(raw)
            doi, title = info["doi"], info["title"] or raw[:200]
            if doi:
                print(f"{name}: doi {doi}")
                await client.crossref_work(doi)
                await client.openalex_doi(doi)
            else:
                print(f"{name}: title {title[:60]}")
                await client.crossref_search(title)
                await client.openalex_search(title)
                r = await client.s2_search(title)
                if not r.ok:
                    print(f"  s2 failed for {name}: {r.error}")
                if info["year"]:
                    await client.crossref_search(title, year=info["year"])
                    await client.openalex_search(title, year=info["year"])
                    r = await client.s2_search(title, year=info["year"])
                    if not r.ok:
                        print(f"  s2 (year) failed for {name}: {r.error}")
    conn = sqlite3.connect(tmp / "rec.sqlite")
    data = {k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM kv")}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"recorded {len(data)} responses -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
