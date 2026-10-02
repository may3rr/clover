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

    async def fake_cloud(model, messages):
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

    async def fake_cloud(model, messages):
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

    async def flaky_cloud(model, messages):
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
    async def bad_cloud(model, messages):
        return "still not json"

    monkeypatch.setattr(llm, "_cloud_call", bad_cloud)
    r = await llm.chat_json("judge", [{"role": "user", "content": "x"}], Out)
    assert r.value is None
