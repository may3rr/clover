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
from citecheck.refs.sources import (
    RetrievalClient,
    SourceResult,
    parse_arxiv_feed,
)
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

    async def dead(url, params, cache_key, **kw):
        return SourceResult(ok=False, error="boom")

    async def dead_arxiv(*a, **kw):
        return SourceResult(ok=False, error="boom")

    monkeypatch.setattr(client, "_get", dead)
    monkeypatch.setattr(client, "_arxiv_query", dead_arxiv)
    check, findings = await verify_references([make_ref(RAWS["vaswani"])], paras, client)
    await client.close()
    assert check[0].status == "unverifiable"
    assert "检索服务暂不可用" in check[0].issues[0]
    assert findings[0].severity == "low"
    assert "暂时无法核验" in findings[0].title


# ---------------------------------------------------------------- T2 fix
# Same-title false positives: a different work sharing the title must not
# produce a mismatch finding. Recorded responses live in
# fixtures/http/same_title_cases.json; the S2 author-query entry was
# reconstructed (S2 429'd during re-recording) with the real NeurIPS 2020
# record — same payload shape S2 returns.

SAME_TITLE = json.loads(
    (FIXTURES / "http" / "same_title_cases.json").read_text())

RAWS2 = {
    "vaswani": RAWS["vaswani"],
    "brown": "[3] Brown TB, Mann B, Ryder N, et al. Language models are "
    "few-shot learners. Advances in Neural Information Processing "
    "Systems. 2020;33:1877-1901.",
}


@pytest.fixture
def same_title_client(tmp_path, monkeypatch):
    cache = Cache(tmp_path / "http.sqlite")
    for k, v in SAME_TITLE.items():
        cache.set(k, v)
    client = RetrievalClient(cache=cache)

    async def fail_transport(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(client._client, "get", fail_transport)
    return client


@pytest.mark.asyncio
async def test_same_title_author_search_rescues(same_title_client, paras):
    """Brown 2020: the broad title search hits a 2026 same-titled work by
    Malakar; the targeted title+surname pass finds the real record."""
    global paras_fixture
    paras_fixture = paras
    check, findings = await _verify(RAWS2["brown"], same_title_client)
    assert check.status == "verified", check.issues
    assert findings == []


@pytest.mark.asyncio
async def test_same_title_wrong_author_gone(same_title_client, paras):
    """Vaswani 2017: even when no source surfaces the 2017 record, the
    author-targeted pass replaces the wrong-author match (Mineault) with
    a Vaswani record — no bogus 首作者不一致 finding."""
    global paras_fixture
    paras_fixture = paras
    check, findings = await _verify(RAWS2["vaswani"], same_title_client)
    assert not any("首作者不一致" in i for i in check.issues)
    assert check.matched and "Vaswani" in check.matched["authors"][0]


# ------------------------------------------------- T2 round 2: arXiv rescue
# Real scenario from the numeric_en run: OpenAlex (shared-IP budget spent,
# keyless) and S2 (429) were both down; only Crossref + arXiv answered.
# fixtures/http/arxiv_rescue_cases.json holds the recorded Crossref title
# searches (containing later same-titled different works) and the recorded
# arXiv Atom feeds that carry the real records. OpenAlex/S2 keys are absent
# -> the offline transport makes them unavailable, exactly like the real run.

RESCUE = json.loads(
    (FIXTURES / "http" / "arxiv_rescue_cases.json").read_text())

RAWS3 = {
    "vaswani": RAWS["vaswani"],   # r1 — same-titled 2024/2025 records on Crossref
    "brown": RAWS2["brown"],      # r3 — Malakar 2026 shares the title
    "mikolov": "[7] Mikolov T, Sutskever I, Chen K, Corrado G, Dean J. "
    "Efficient estimation of word representations in vector space. "
    "International Conference on Learning Representations. 2013.",  # r7 — Bhatta 2020
}


@pytest.fixture
def rescue_client(tmp_path, monkeypatch):
    cache = Cache(tmp_path / "http.sqlite")
    for k, v in RESCUE.items():
        cache.set(k, v)
    client = RetrievalClient(cache=cache)

    async def fail_transport(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(client._client, "get", fail_transport)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["vaswani", "brown", "mikolov"])
async def test_arxiv_rescues_same_title(case, rescue_client, paras):
    """With OpenAlex/S2 down, a later same-titled Crossref record used to
    produce a false mismatch. The arXiv record (preprint, possibly earlier
    year) verifies the real work."""
    global paras_fixture
    paras_fixture = paras
    check, findings = await _verify(RAWS3[case], rescue_client)
    assert check.status == "verified", f"{case}: {check.issues}"
    assert check.matched and check.matched.get("source") == "arxiv"
    assert findings == []


@pytest.mark.asyncio
async def test_both_differ_record_ignored(rescue_client, paras, monkeypatch):
    """Rule (c): a title-matched record disagreeing on BOTH first author
    and year is a different work — ignored entirely, no mismatch. With no
    usable record anywhere -> not_found (all four sources responded)."""
    global paras_fixture
    paras_fixture = paras
    wrong = {
        "source": "crossref",
        "title": "Attention Is All You Need",
        "authors": ["Pat Mineault"],   # wrong author AND wrong year
        "year": 2025, "venue": "x", "doi": None, "url": None,
        "abstract": None, "pdf_url": None, "arxiv_id": None, "alt_year": None,
    }
    empty_arxiv = next(
        v["xml"] for v in RECORDED.values()
        if isinstance(v, dict) and v.get("xml")
        and not parse_arxiv_feed(v["xml"])
    )

    async def fake_crossref(query, rows=5, year=None, author=None):
        return SourceResult(ok=True, data=[wrong])

    async def fake_empty(*a, **kw):
        return SourceResult(ok=True, data=[])

    async def fake_arxiv(title, author=None, max_results=5):
        return SourceResult(ok=True, data=parse_arxiv_feed(empty_arxiv))

    monkeypatch.setattr(rescue_client, "crossref_search", fake_crossref)
    monkeypatch.setattr(rescue_client, "openalex_search", fake_empty)
    monkeypatch.setattr(rescue_client, "s2_search", fake_empty)
    monkeypatch.setattr(rescue_client, "arxiv_search", fake_arxiv)
    check, findings = await _verify(RAWS["vaswani"], rescue_client)
    assert check.status == "not_found"
    assert check.issues == ["四个数据库均未检索到相符文献"]
    assert findings[0].severity == "high"


@pytest.mark.asyncio
async def test_arxiv_feed_parser():
    """The Atom parser yields normalized hits: title, authors, year,
    arxiv_id, doi, summary->abstract, pdf_url."""
    xml_entry = next(
        v["xml"] for v in RESCUE.values()
        if isinstance(v, dict) and v.get("xml") and parse_arxiv_feed(v["xml"])
    )
    hits = parse_arxiv_feed(xml_entry)
    assert hits
    h = hits[0]
    assert h["source"] == "arxiv"
    assert h["title"] and h["authors"] and h["year"]
    assert h["arxiv_id"] and "v" not in h["arxiv_id"][-2:]
    assert h["pdf_url"].endswith(h["arxiv_id"])
    assert h["alt_year"] == h["year"]


@pytest.mark.asyncio
async def test_source_api_keys(tmp_path, monkeypatch):
    """OPENALEX_API_KEY lands as ?api_key=, S2_API_KEY as x-api-key header."""
    client = RetrievalClient(cache=Cache(tmp_path / "k.sqlite"))
    client._openalex_key = "OAKEY"
    client._s2_key = "S2KEY"
    seen: list[dict] = []

    async def capture(url, params=None, headers=None, **kw):
        seen.append({"url": url, "params": params or {},
                     "headers": headers or {}})
        body = {"results": []} if "openalex" in url else {"data": []}
        return httpx.Response(
            200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(client._client, "get", capture)
    await client.openalex_search("anything")
    await client.s2_search("anything")
    assert seen[0]["params"]["api_key"] == "OAKEY"
    assert seen[1]["headers"]["x-api-key"] == "S2KEY"
