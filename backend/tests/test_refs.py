"""T2 tests: reference verification replaying recorded API responses.

tests/fixtures/http/refs_cases.json holds real Crossref/OpenAlex/S2
responses keyed by the same cache keys the client uses — no network in
tests. The 'all sources down' case forces failures via a stubbed _get.
"""

import json
from pathlib import Path

import httpx
import pytest

from citecheck.cache import Cache
from citecheck.refs.sources import RetrievalClient, SourceResult
from citecheck.refs.structure import parse_reference
from citecheck.refs.verify import verify_references
from citecheck.schema import Paragraph, Reference

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = json.loads((FIXTURES / "http" / "refs_cases.json").read_text())

# raw strings must match tests/fixtures/record_http.py CASES
RAWS = {
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
}


def make_ref(raw: str, rid: str = "r1") -> Reference:
    info = parse_reference(raw)
    return Reference(
        id=rid, raw=raw, title=info["title"], authors=info["authors"],
        year=info["year"], venue=info["venue"], doi=info["doi"],
        lang=info["lang"], paragraph_id="p9", label=info["label"],
    )


@pytest.fixture
def recorded_client(tmp_path, monkeypatch):
    """RetrievalClient whose Cache is seeded with recorded responses;
    any cache miss hits a transport that always fails (no network)."""
    cache = Cache(tmp_path / "http.sqlite")
    for k, v in RECORDED.items():
        cache.set(k, v)
    client = RetrievalClient(cache=cache)

    async def fail_transport(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(client._client, "get", fail_transport)
    return client


@pytest.fixture
def paras():
    return [Paragraph(id="p9", section_id="s9",
                      text="x" * 60, char_offset=0)]


async def _verify(raw: str, client) -> tuple[object, list]:
    checks, findings = await verify_references([make_ref(raw)], paras_fixture, client)
    return checks[0], findings


paras_fixture: list[Paragraph] = []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["vaswani", "devlin", "lewis"])
async def test_real_refs_verified(case, recorded_client, paras):
    global paras_fixture
    paras_fixture = paras
    check, findings = await _verify(RAWS[case], recorded_client)
    assert check.status == "verified", f"{case}: {check.issues}"
    assert check.matched and check.matched["title"]
    assert findings == []


@pytest.mark.asyncio
async def test_wrong_year_mismatch(recorded_client, paras):
    global paras_fixture
    paras_fixture = paras
    check, findings = await _verify(RAWS["he_wrong_year"], recorded_client)
    assert check.status == "mismatch"
    assert any("年份不一致" in i for i in check.issues)
    assert findings and findings[0].severity == "medium"


@pytest.mark.asyncio
async def test_fabricated_not_found(recorded_client, paras):
    global paras_fixture
    paras_fixture = paras
    check, findings = await _verify(RAWS["fabricated"], recorded_client)
    assert check.status == "not_found", check.issues
    assert findings[0].severity == "high"
    assert "未能在数据库中找到" in findings[0].title


@pytest.mark.asyncio
async def test_chinese_never_not_found(recorded_client, paras):
    global paras_fixture
    paras_fixture = paras
    check, _ = await _verify(RAWS["zh_ref"], recorded_client)
    assert check.status in {"verified", "unverifiable"}


@pytest.mark.asyncio
async def test_doi_points_elsewhere(recorded_client, paras):
    global paras_fixture
    paras_fixture = paras
    check, findings = await _verify(RAWS["doi_elsewhere"], recorded_client)
    assert check.status == "mismatch"
    assert any("DOI 指向另一篇文献" in i for i in check.issues)


@pytest.mark.asyncio
async def test_all_sources_down_unverifiable(tmp_path, paras, monkeypatch):
    client = RetrievalClient(cache=Cache(tmp_path / "none.sqlite"))

    async def dead(url, params, cache_key):
        return SourceResult(ok=False, error="boom")

    monkeypatch.setattr(client, "_get", dead)
    check, findings = await verify_references([make_ref(RAWS["vaswani"])], paras, client)
    await client.close()
    assert check[0].status == "unverifiable"
    assert "检索服务暂不可用" in check[0].issues[0]
    assert findings[0].severity == "low"
    assert "暂时无法核验" in findings[0].title
