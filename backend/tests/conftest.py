import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CITECHECK_CACHE", str(tmp_path / "cache.sqlite"))
    # no embedding calls from tests; embedding tests patch the client
    monkeypatch.setenv("CITECHECK_EMBED", "0")
    monkeypatch.setenv("CITECHECK_RERANK", "0")


@pytest.fixture(autouse=True)
def _skip_live(request):
    if request.node.get_closest_marker("live") and os.environ.get("CITECHECK_LIVE") != "1":
        pytest.skip("live test: set CITECHECK_LIVE=1 to run")


@pytest.fixture(autouse=True)
def _reset_source_cooldown():
    """Rate-limit cooldowns are process-wide; one test's 429 must not take
    a source down for the next test."""
    from citecheck.refs import sources
    sources._cooldown_until.clear()
    yield
    sources._cooldown_until.clear()
