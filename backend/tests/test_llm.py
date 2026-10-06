"""llm/ module tests: routing, cache, retry, stats. Network is faked."""

import pytest
from pydantic import BaseModel

from citecheck.llm import client as llm
from citecheck.llm import local, router
from citecheck.config import Settings, get_settings


class Out(BaseModel):
    label: str
    n: int = 0


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch, tmp_path):
    """Isolated cache + cloud stubs per test."""
    from citecheck.cache import Cache

    cache = Cache(tmp_path / "llm.sqlite")
    monkeypatch.setattr(llm, "_cache", cache)
    monkeypatch.setattr(llm, "_cloud_client", None)
    monkeypatch.setattr(llm, "_cloud_sem", None)
    yield


def test_route_order():
    s = Settings()
    s.llm.local.enabled = True
    assert router.route_order("extract", s) == ["local", "cloud"]
    assert router.route_order("judge", s) == ["cloud"]
    s.llm.local.enabled = False
    assert router.route_order("extract", s) == ["cloud"]


@pytest.mark.asyncio
async def test_cloud_success_and_cache(monkeypatch):
    calls = []

    async def fake_cloud(model, messages, task):
        calls.append(messages)
        return '{"label": "ok", "n": 1}'

    monkeypatch.setattr(llm, "_cloud_call", fake_cloud)
    with llm.stats_scope() as stats:
        r1 = await llm.chat_json("judge", [{"role": "user", "content": "hi"}], Out)
        r2 = await llm.chat_json("judge", [{"role": "user", "content": "hi"}], Out)
    assert r1.value == Out(label="ok", n=1) and r1.route == "cloud"
    assert r2.cached and r2.value == Out(label="ok", n=1)
    assert len(calls) == 1
    assert stats.cloud == 2  # cache hits count by their original route


@pytest.mark.asyncio
async def test_local_fallback_to_cloud(monkeypatch):
    async def bad_local(messages, max_tokens=1024):
        raise RuntimeError("local down")

    async def fake_cloud(model, messages, task):
        return '{"label": "cloud"}'

    monkeypatch.setattr(local, "generate_or_raise", bad_local)
    monkeypatch.setattr(llm, "_cloud_call", fake_cloud)
    monkeypatch.setattr(llm, "get_settings",
                        lambda: Settings(llm={"local": {"enabled": True}}))
    with llm.stats_scope() as stats:
        r = await llm.chat_json("extract", [{"role": "user", "content": "x"}], Out)
    assert r.route == "cloud" and r.value.label == "cloud"
    assert stats.local == 0 and stats.cloud == 1


@pytest.mark.asyncio
async def test_retry_once_on_invalid_json(monkeypatch):
    seen = []

    async def flaky_cloud(model, messages, task):
        seen.append(len(messages))
        if len(seen) == 1:
            return "not json"
        return '{"label": "fixed"}'

    monkeypatch.setattr(llm, "_cloud_call", flaky_cloud)
    r = await llm.chat_json("judge", [{"role": "user", "content": "x"}], Out)
    assert r.value.label == "fixed"
    assert len(seen) == 2 and seen[1] > seen[0]  # retry appended messages


@pytest.mark.asyncio
async def test_invalid_twice_returns_none(monkeypatch):
    async def bad_cloud(model, messages, task):
        return "still not json"

    monkeypatch.setattr(llm, "_cloud_call", bad_cloud)
    r = await llm.chat_json("judge", [{"role": "user", "content": "x"}], Out)
    assert r.value is None


@pytest.mark.asyncio
async def test_usage_log_records_cache_hits(monkeypatch):
    """Cache hits persist a llm_usage row (0 tokens, cached=1)."""
    async def fake_cloud(model, messages, task):
        return '{"label": "ok"}'

    monkeypatch.setattr(llm, "_cloud_call", fake_cloud)
    await llm.chat_json("judge", [{"role": "user", "content": "hi"}], Out)
    await llm.chat_json("judge", [{"role": "user", "content": "hi"}], Out)
    rows = llm._get_cache().usage_summary()
    assert len(rows) == 1
    assert rows[0]["calls"] == 1 and rows[0]["cached_calls"] == 1
    assert rows[0]["provider"] == "dashscope"
    assert rows[0]["prompt"] == 0 and rows[0]["completion"] == 0


def test_cache_key_uses_cache_version(monkeypatch):
    """Bumping settings.cache_version invalidates every cached verdict —
    the version is part of the key."""
    msgs = [{"role": "user", "content": "x"}]
    base = get_settings()
    monkeypatch.setattr(
        llm, "get_settings",
        lambda: base.model_copy(update={"cache_version": "1"}))
    k1 = llm._cache_key("qwen-plus", msgs)
    monkeypatch.setattr(
        llm, "get_settings",
        lambda: base.model_copy(update={"cache_version": "2"}))
    k2 = llm._cache_key("qwen-plus", msgs)
    assert k1 != k2
    assert k1.startswith("qwen-plus|") and k2.startswith("qwen-plus|")


@pytest.mark.asyncio
async def test_cache_version_bump_invalidates_verdicts(monkeypatch):
    """End to end: same prompt cached under v1 is a miss under v2."""
    async def fake_cloud(model, messages, task):
        return '{"label": "ok"}'

    monkeypatch.setattr(llm, "_cloud_call", fake_cloud)
    base = get_settings()
    monkeypatch.setattr(
        llm, "get_settings",
        lambda: base.model_copy(update={"cache_version": "1"}))
    r1 = await llm.chat_json("judge", [{"role": "user", "content": "hi"}], Out)
    monkeypatch.setattr(
        llm, "get_settings",
        lambda: base.model_copy(update={"cache_version": "2"}))
    r2 = await llm.chat_json("judge", [{"role": "user", "content": "hi"}], Out)
    assert not r1.cached and r2.cached is False


def test_priority_semaphore_orders_waiters():
    """A freed slot goes to the most urgent waiter, FIFO within a level;
    cancelled waiters don't leak slots."""
    import asyncio

    from citecheck.llm.client import PrioritySemaphore

    async def run():
        sem = PrioritySemaphore(1)
        order: list[str] = []
        await sem.acquire(0)  # hold the only slot

        async def worker(name, prio):
            async with sem.slot(prio):
                order.append(name)

        tasks = [asyncio.create_task(worker(n, p)) for n, p in
                 [("typo1", 3), ("typo2", 3), ("judge", 1), ("struct", 0)]]
        doomed = asyncio.create_task(worker("cancelled", 0))
        await asyncio.sleep(0)
        doomed.cancel()
        await asyncio.sleep(0)
        sem.release()
        await asyncio.gather(*tasks)
        assert order == ["struct", "judge", "typo1", "typo2"]
        # all slots returned: an immediate acquire succeeds
        await asyncio.wait_for(sem.acquire(2), 0.1)

    asyncio.run(run())
