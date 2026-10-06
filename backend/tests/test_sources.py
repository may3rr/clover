"""RetrievalClient HTTP behavior: status-code classification, retry
backoff, and circuit-breaker rules. No network — the transport is
stubbed and asyncio.sleep/arxiv_throttle are no-ops."""

import asyncio

import httpx
import pytest

from citecheck.cache import Cache
from citecheck.refs import sources
from citecheck.refs.sources import ARXIV_API, RetrievalClient

FEED = (
    '<?xml version="1.0"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    "<entry><id>http://arxiv.org/abs/1706.03762v7</id>"
    "<title>Attention Is All You Need</title>"
    "<published>2017-06-12T00:00:00Z</published>"
    "<author><name>Ashish Vaswani</name></author>"
    "<summary>Attention paper.</summary></entry>"
    "</feed>"
)


@pytest.fixture
def client(tmp_path):
    return RetrievalClient(cache=Cache(tmp_path / "s.sqlite"))


@pytest.fixture
def no_sleep(monkeypatch):
    """Record sleep durations instead of actually sleeping."""
    calls: list[float] = []

    async def fake_sleep(delay):
        calls.append(delay)

    async def noop_throttle():
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sources, "arxiv_throttle", noop_throttle)
    return calls


def _transport(monkeypatch, client, responses):
    """Stub client._client.get to yield the given responses/exceptions."""
    calls: list[dict] = []
    it = iter(responses)

    async def fake_get(url, params=None, headers=None, **kw):
        calls.append({"url": url, "params": params or {}})
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(client._client, "get", fake_get)
    return calls


def _resp(url, status, json_body=None, text=""):
    req = httpx.Request("GET", url)
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=req)
    return httpx.Response(status, text=text, request=req)


# ---------------------------------------------------------------- 4xx

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 403, 404])
async def test_4xx_no_retry_no_breaker(client, no_sleep, monkeypatch,
                                       status):
    """A 4xx (non-429) means the source answered: 'record absent' or
    'invalid query'. One attempt, no backoff, no circuit-breaker count."""
    url = "https://api.crossref.org/works"
    calls = _transport(monkeypatch, client,
                       [_resp(url, status, text="nope")])
    r = await client.crossref_search("anything")
    assert r.ok and r.data is None
    assert len(calls) == 1
    assert no_sleep == []
    assert client._consecutive_fails.get("crossref", 0) == 0
    assert "crossref" not in client._down


@pytest.mark.asyncio
async def test_4xx_doi_lookup_means_resolved_no_work(client, monkeypatch):
    """On a DOI lookup a 404 is 'resolved endpoint, no work': ok=True with
    data=None, so verify.py counts the source as answered."""
    url = "https://api.crossref.org/works/10.x/abc"
    _transport(monkeypatch, client, [_resp(url, 404, text="nope")])
    r = await client.crossref_work("10.x/abc")
    assert r.ok and r.data is None
    assert "crossref" not in client._down


# ---------------------------------------------------------------- 5xx

@pytest.mark.asyncio
async def test_5xx_retries_with_backoff(client, no_sleep, monkeypatch):
    url = "https://api.crossref.org/works"
    calls = _transport(monkeypatch, client,
                       [_resp(url, 500, text="boom")] * 3)
    r = await client.crossref_search("anything")
    assert not r.ok and r.error == "HTTP 500"
    assert len(calls) == 3  # 1 try + 2 retries
    # backoff before each follow-up attempt, like transport errors (the
    # existing pattern also sleeps once after the final failed attempt)
    assert no_sleep == [1, 2, 4]
    assert client._consecutive_fails["crossref"] == 1
    assert "crossref" not in client._down  # one burst != two failures


# ---------------------------------------------------------------- 429

@pytest.mark.asyncio
async def test_429_retries_once_then_ok(client, no_sleep, monkeypatch):
    url = "https://api.openalex.org/works"
    calls = _transport(monkeypatch, client, [
        _resp(url, 429, text="slow down"),
        _resp(url, 200, json_body={"results": []}),
    ])
    r = await client.openalex_search("anything")
    assert r.ok and r.data == []
    assert len(calls) == 2
    assert no_sleep == [1]  # single 429 backoff, then success
    assert "openalex" not in client._down


@pytest.mark.asyncio
async def test_429_backs_off_and_recovers(client, no_sleep, monkeypatch):
    """Crossref/OpenAlex 429 = slow down: honor Retry-After, retry, and
    keep the source up once it answers."""
    url = "https://api.crossref.org/works"
    req = httpx.Request("GET", url)
    _transport(monkeypatch, client, [
        httpx.Response(429, headers={"Retry-After": "3"}, request=req),
        _resp(url, 200, json_body={"message": {"items": []}}),
    ])
    r = await client.crossref_search("anything")
    assert r.ok and no_sleep == [3.0]
    assert "crossref" not in client._down


@pytest.mark.asyncio
async def test_persistent_429_takes_source_down_for_run_only(
        client, no_sleep, monkeypatch):
    url = "https://api.openalex.org/works"
    _transport(monkeypatch, client, [
        _resp(url, 429, text="slow down")] * 3)
    r = await client.openalex_search("anything")
    assert not r.ok and r.error == "429"
    assert "openalex" in client._down
    # throttling, not an exhausted budget: the next run starts fresh
    assert "openalex" not in sources._cooldown_until


# ---------------------------------------------------------------- arXiv

@pytest.mark.asyncio
async def test_arxiv_single_failure_no_breaker(client, no_sleep,
                                               monkeypatch):
    """One transport failure + success after the retry: source stays up."""
    calls = _transport(monkeypatch, client, [
        httpx.ConnectError("offline"),
        _resp(ARXIV_API, 200, text=FEED),
    ])
    r = await client.arxiv_search("Attention Is All You Need")
    assert r.ok and len(r.data) == 1
    assert len(calls) == 2  # one retry
    assert no_sleep == [1]  # backoff after the throttle gap
    assert client._consecutive_fails.get("arxiv", 0) == 0
    assert "arxiv" not in client._down


@pytest.mark.asyncio
async def test_arxiv_two_consecutive_failures_breaker(client, no_sleep,
                                                      monkeypatch):
    """Aligned with the other sources: a single failed query only counts
    toward the breaker; two consecutive failed queries take arXiv down."""
    calls = _transport(monkeypatch, client,
                       [_resp(ARXIV_API, 429, text="slow down")] * 4)
    r1 = await client.arxiv_search("Attention Is All You Need")
    assert not r1.ok
    assert "arxiv" not in client._down
    assert client._consecutive_fails["arxiv"] == 1

    r2 = await client.arxiv_search("BERT pre-training")
    assert not r2.ok
    assert "arxiv" in client._down
    assert len(calls) == 4  # 2 attempts per query, no third try

    # fail fast from now on
    r3 = await client.arxiv_search("something else")
    assert not r3.ok and r3.error == "source unavailable"
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_arxiv_success_resets_breaker_count(client, no_sleep,
                                                  monkeypatch):
    _transport(monkeypatch, client, [
        httpx.ConnectError("offline"),
        _resp(ARXIV_API, 200, text=FEED),
        httpx.ConnectError("offline"),
        _resp(ARXIV_API, 200, text=FEED),
    ])
    for _ in range(2):
        r = await client.arxiv_search("Attention Is All You Need")
        assert r.ok
    assert "arxiv" not in client._down


def test_429_cooldown_spans_runs(monkeypatch, tmp_path, no_sleep):
    """A source that hit its rate limit stays skipped for the next client
    (next pipeline run) in this process, without a request."""
    first = RetrievalClient(cache=Cache(tmp_path / "a.sqlite"))
    calls = _transport(monkeypatch, first, [
        httpx.Response(429, text="slow down"),
        httpx.Response(429, text="slow down"),
    ])
    r = asyncio.run(first.s2_search("Attention is all you need"))
    assert not r.ok and len(calls) == 2
    second = RetrievalClient(cache=Cache(tmp_path / "b.sqlite"))
    calls2 = _transport(monkeypatch, second, [])
    r2 = asyncio.run(second.s2_search("Attention is all you need"))
    assert not r2.ok and r2.error == "source unavailable" and calls2 == []


def test_404_answer_is_cached(monkeypatch, tmp_path, no_sleep):
    cache = Cache(tmp_path / "c.sqlite")
    client = RetrievalClient(cache=cache)
    calls = _transport(monkeypatch, client, [httpx.Response(404)])
    r = asyncio.run(client.crossref_work("10.1234/missing"))
    assert r.ok and r.data is None and len(calls) == 1
    again = RetrievalClient(cache=cache)
    calls2 = _transport(monkeypatch, again, [])
    r2 = asyncio.run(again.crossref_work("10.1234/missing"))
    assert r2.ok and r2.data is None and calls2 == []


def test_arxiv_throttle_survives_new_event_loops(monkeypatch):
    """Batch scripts call asyncio.run() once per paper; the throttle lock
    must not stay bound to the first loop."""
    monkeypatch.setattr(sources, "_arxiv_last", 0.0)

    async def hold_and_wait():
        # contend for the lock so it actually binds to this loop
        await asyncio.gather(sources.arxiv_throttle(),
                             sources.arxiv_throttle())

    real_sleep = asyncio.sleep

    async def fast_sleep(_d):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    asyncio.run(hold_and_wait())
    asyncio.run(hold_and_wait())  # used to raise "bound to a different loop"
