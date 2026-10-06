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
from citecheck.refs.verify import _evaluate, verify_references
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
async def test_fabricated_not_found_s2_limited(recorded_client, paras, monkeypatch):
    """New not_found rule: S2 is optional — a fabricated ref reaches
    not_found when Crossref + OpenAlex + arXiv all answered with no match,
    even while S2 is rate-limited/down."""
    global paras_fixture
    paras_fixture = paras

    async def dead_s2(*a, **kw):
        return SourceResult(ok=False, error="429")

    monkeypatch.setattr(recorded_client, "s2_search", dead_s2)
    check, findings = await _verify(RAWS["fabricated"], recorded_client)
    assert check.status == "not_found", check.issues
    assert findings[0].severity == "high"


@pytest.mark.asyncio
async def test_required_source_down_unverifiable(recorded_client, paras, monkeypatch):
    """If any of Crossref/OpenAlex/arXiv was unavailable the same ref is
    unverifiable, not not_found — an errored source is not 'no hit'."""
    global paras_fixture
    paras_fixture = paras

    async def dead_oa(*a, **kw):
        return SourceResult(ok=False, error="429")

    monkeypatch.setattr(recorded_client, "openalex_search", dead_oa)
    check, findings = await _verify(RAWS["fabricated"], recorded_client)
    assert check.status == "unverifiable"
    assert "检索服务暂不可用" in check.issues[0]
    assert findings[0].severity == "low"


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
    async def fake_crossref(query, rows=5, year=None, author=None):
        return SourceResult(ok=True, data=[wrong])

    async def fake_empty(*a, **kw):
        return SourceResult(ok=True, data=[])

    monkeypatch.setattr(rescue_client, "crossref_search", fake_crossref)
    monkeypatch.setattr(rescue_client, "openalex_search", fake_empty)
    monkeypatch.setattr(rescue_client, "s2_search", fake_empty)
    # arXiv answered but found nothing (the recorded rescue feed must not
    # leak in here — verification queries go through the batch method)
    monkeypatch.setattr(rescue_client, "arxiv_search_batch", fake_empty)
    monkeypatch.setattr(rescue_client, "arxiv_loose_search", fake_empty)
    monkeypatch.setattr(rescue_client, "arxiv_search", fake_empty)
    check, findings = await _verify(RAWS["vaswani"], rescue_client)
    assert check.status == "not_found"
    assert check.issues == [
        "Crossref、OpenAlex、Semantic Scholar、arXiv均未检索到相符文献"
    ]
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


@pytest.mark.asyncio
async def test_arxiv_batch_one_request(tmp_path, monkeypatch):
    """Batched title lookup: several titles go into ONE ti:"a" OR ti:"b"
    request, and entries come back for the caller to distribute."""
    client = RetrievalClient(cache=Cache(tmp_path / "b.sqlite"))
    calls: list[str] = []

    async def capture(url, params=None, headers=None, **kw):
        calls.append((params or {}).get("search_query", ""))
        xml = (
            '<?xml version="1.0"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            "<entry><id>http://arxiv.org/abs/1706.03762v7</id>"
            "<title>Attention Is All You Need</title>"
            "<published>2017-06-12T00:00:00Z</published>"
            "<author><name>Ashish Vaswani</name></author>"
            "<summary>Attention paper.</summary></entry>"
            "</feed>"
        )
        return httpx.Response(
            200, text=xml, request=httpx.Request("GET", url))

    monkeypatch.setattr(client._client, "get", capture)
    r = await client.arxiv_search_batch(
        ["Attention is all you need", "BERT: pre-training"])
    assert r.ok and len(r.data) == 1 and r.data[0]["source"] == "arxiv"
    assert len(calls) == 1
    assert 'ti:"Attention is all you need"' in calls[0]
    assert 'ti:"BERT: pre-training"' in calls[0]
    assert " OR " in calls[0]
    await client.close()


# ------------------------------------------- code-review fixes: _evaluate

BERT_TITLE = ("BERT: Pre-training of deep bidirectional transformers for "
              "language understanding")


def _hit(title=BERT_TITLE, authors=("Jacob Devlin", "Ming-Wei Chang"),
         doi="10.18653/v1/N19-1423", source="crossref", year=2019) -> dict:
    return {"source": source, "title": title, "authors": list(authors),
            "year": year, "venue": "NAACL", "doi": doi, "url": None,
            "abstract": None, "pdf_url": None, "arxiv_id": None,
            "alt_year": None}


def test_second_author_mismatch_flagged():
    """A wrong SECOND author used to pass unnoticed (only the first-author
    surname was compared)."""
    ref = make_ref(RAWS["devlin"])  # Devlin, Chang, Lee, Toutanova
    hit = _hit(authors=("Jacob Devlin", "Kenton Lee"))  # 2nd author wrong
    issues, author_diff, _ = _evaluate(ref, hit)
    assert any("第二作者不一致" in i for i in issues)
    assert author_diff is False  # first-author logic untouched


def test_second_author_match_no_issue():
    ref = make_ref(RAWS["devlin"])
    issues, _, _ = _evaluate(ref, _hit())
    assert not any("第二作者" in i for i in issues)


def test_arxiv_record_exempt_from_second_author_check():
    """arXiv preprint author lists drift between versions (the word2vec
    preprint omits Sutskever) — the venue record is authoritative."""
    ref = make_ref(RAWS["devlin"])
    hit = _hit(source="arxiv", authors=("Jacob Devlin", "Kenton Lee"))
    issues, _, _ = _evaluate(ref, hit)
    assert not any("第二作者" in i for i in issues)


def test_arxiv_resolver_doi_not_a_mismatch():
    """A preprint record whose doi is arXiv's own resolver DOI must not
    contradict the journal DOI written in the manuscript."""
    ref = make_ref(RAWS["devlin"])  # doi 10.18653/v1/N19-1423
    hit = _hit(doi="10.48550/arXiv.1810.04805", source="arxiv")
    issues, _, _ = _evaluate(ref, hit)
    assert not any("DOI 不一致" in i for i in issues)
    # case-insensitive resolver prefix
    hit = _hit(doi="10.48550/ARXIV.1810.04805", source="crossref")
    issues, _, _ = _evaluate(ref, hit)
    assert not any("DOI 不一致" in i for i in issues)


def test_real_doi_mismatch_still_flagged():
    ref = make_ref(RAWS["devlin"])
    issues, _, _ = _evaluate(ref, _hit(doi="10.18653/v1/N19-9999"))
    assert any("DOI 不一致" in i for i in issues)


# --------------------------- code-review fixes: DOI resolves to other work

def _doi_result(hit):
    async def f(*a, **kw):
        return SourceResult(ok=True, data=hit)

    return f


def _search_result(hit):
    async def f(*a, **kw):
        return SourceResult(ok=True, data=[hit] if hit else [])

    return f


@pytest.mark.asyncio
async def test_doi_resolves_to_other_work_mismatch(recorded_client, paras,
                                                   monkeypatch):
    """The manuscript DOI resolves to a record with a clearly different
    title while another record matches the title: mismatch, and the issue
    says the DOI points at another work."""
    global paras_fixture
    paras_fixture = paras
    other = _hit(title="Neural architectures for part-of-speech tagging",
                 authors=("Smith J", "Lee K"), year=2019,
                 doi="10.18653/v1/N19-1423")
    real = _hit(doi="10.48550/arXiv.1810.04805", source="openalex")
    monkeypatch.setattr(recorded_client, "crossref_work",
                        _doi_result(other))
    monkeypatch.setattr(recorded_client, "openalex_doi", _doi_result(real))
    for name in ("arxiv_search_batch", "arxiv_loose_search", "arxiv_search"):
        monkeypatch.setattr(recorded_client, name, _search_result(None))
    check, findings = await _verify(RAWS["devlin"], recorded_client)
    assert check.status == "mismatch"
    assert any("DOI 解析到另一篇文献" in i for i in check.issues)
    assert findings and findings[0].severity == "medium"


@pytest.mark.asyncio
async def test_doi_other_suppressed_when_matched_record_carries_doi(
        recorded_client, paras, monkeypatch):
    """Guard against the DOI-relaxed title path: the title-matched record
    itself has the manuscript DOI (same work, messy metadata) — no
    'DOI 解析到另一篇文献'."""
    global paras_fixture
    paras_fixture = paras
    same = _hit(doi="10.18653/v1/N19-1423")  # carries the manuscript DOI
    junk = _hit(title="Completely unrelated proceedings volume",
                doi="10.18653/v1/N19-1423")
    monkeypatch.setattr(recorded_client, "crossref_work", _doi_result(junk))
    monkeypatch.setattr(recorded_client, "openalex_doi", _doi_result(same))
    for name in ("arxiv_search_batch", "arxiv_loose_search", "arxiv_search"):
        monkeypatch.setattr(recorded_client, name, _search_result(None))
    check, _ = await _verify(RAWS["devlin"], recorded_client)
    assert check.status == "verified", check.issues
    assert not any("DOI 解析到另一篇文献" in i for i in check.issues)


def test_dropped_subtitle_still_matches():
    """'A decomposable attention model' (Attention Is All You Need's bib)
    is the 2016 Parikh paper '... for Natural Language Inference' — a
    dropped subtitle must not turn a real work into not_found."""
    from citecheck.refs.verify import _select
    from citecheck.schema import Reference
    ref = Reference(id="r1", raw="x", title="A decomposable attention model",
                    authors=["Ankur Parikh", "Oscar Täckström"], year=2016)
    full = _hit(title="A Decomposable Attention Model for Natural Language "
                      "Inference", authors=("Ankur Parikh", "Oscar Täckström"),
                year=2016, doi="10.18653/v1/D16-1244")
    matches, _ = _select(ref, [full])
    assert matches and not matches[0][2]
    # same leading words but a different first author: not the same work
    other = _hit(title=full["title"], authors=("Someone Else", "Oscar Täckström"),
                 year=2016, doi=None)
    assert _select(ref, [other])[0] == []
    # too short to be a safe prefix ("Attention models" vs longer title)
    short = Reference(id="r2", raw="x", title="Attention model",
                      authors=["Ankur Parikh"], year=2016)
    assert _select(short, [full])[0] == []


def test_grey_literature_is_not_called_nonexistent():
    """Tech reports, web pages and venue-less entries aren't indexed by the
    databases: when nothing is found they are unverifiable, never
    not_found. A fabricated paper with a venue stays not_found."""
    from citecheck.refs.verify import _conclude
    from citecheck.schema import Reference
    responded = {"crossref", "openalex", "arxiv"}
    gpt = Reference(id="r1", raw="Alec Radford, Karthik Narasimhan. 2018. "
                    "Improving language understanding with unsupervised "
                    "learning. Technical report, OpenAI.", lang="en",
                    title="Improving language understanding", year=2018)
    quora = Reference(id="r2", raw="Zihan Chen. 2018. Quora question pairs.",
                      lang="en", title="Quora question pairs", year=2018)
    fake = Reference(id="r3", raw="Wei Zhou. 2016. Sparse recurrent attention."
                     " Transactions on Neural Sequence Modeling, 4(2).",
                     lang="en", title="Sparse recurrent attention", year=2016,
                     venue="Transactions on Neural Sequence Modeling")
    assert _conclude(gpt, [], None, responded, 100)[0].status == "unverifiable"
    assert _conclude(quora, [], None, responded, 100)[0].status == "unverifiable"
    assert _conclude(fake, [], None, responded, 100)[0].status == "not_found"


def test_explicit_arxiv_id_verifies_without_title_search():
    """'Maskgan: ... filling in the\\_' defeats keyword search; the entry's
    own arXiv id resolves it exactly, and no title search is spent."""
    import asyncio

    from citecheck.refs.verify import verify_references
    from citecheck.schema import Reference

    feed_hit = {"source": "arxiv", "title": "MaskGAN: Better Text "
                "Generation via Filling in the______",
                "authors": ["William Fedus", "Ian Goodfellow", "Andrew M. Dai"],
                "year": 2018, "venue": "arXiv", "doi": None, "url": None,
                "abstract": None, "pdf_url": None, "arxiv_id": "1801.07736",
                "alt_year": 2018}

    class Fake:
        searched = 0

        async def arxiv_by_ids(self, ids):
            from citecheck.refs.sources import SourceResult
            assert ids == ["1801.07736"]
            return SourceResult(ok=True, data=[feed_hit])

        def __getattr__(self, name):  # any title search is a failure here
            async def boom(*a, **k):
                Fake.searched += 1
                raise AssertionError(f"unexpected {name}")
            return boom

    ref = Reference(
        id="r1", lang="en", year=2018,
        raw="William Fedus, Ian Goodfellow, and Andrew M Dai. 2018. Maskgan: "
            "Better text generation via filling in the_. arXiv preprint "
            "arXiv:1801.07736.",
        title="Maskgan: Better text generation via filling in the_",
        authors=["William Fedus", "Ian Goodfellow", "Andrew M Dai"])
    checks, _ = asyncio.run(verify_references([ref], [], Fake()))
    assert checks[0].status == "verified" and Fake.searched == 0


def test_retitled_arxiv_paper_matches_by_its_id():
    """nuQmm was retitled LUT-GEMM on arXiv: the entry's own arXiv id with
    agreeing first author and year still identifies the work."""
    from citecheck.refs.verify import _select
    from citecheck.schema import Reference
    ref = Reference(id="r1", raw="x arXiv:2206.09557", year=2022,
                    title="nuQmm: Quantized MatMul for Efficient Inference",
                    authors=["Gunho Park", "Baeseong Park"])
    rec = _hit(title="LUT-GEMM: Quantized Matrix Multiplication based on LUTs",
               authors=("Gunho Park", "Baeseong Park"), year=2022, doi=None,
               source="arxiv")
    assert _select(ref, [rec])[0] == []                 # title search: no
    matches, _ = _select(ref, [{**rec, "via_id": True}])  # by its own id: yes
    assert matches and not matches[0][2]
    wrong = {**rec, "via_id": True, "authors": ["Someone Else"]}
    assert _select(ref, [wrong])[0] == []
