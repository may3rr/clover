import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CITECHECK_CACHE", str(tmp_path / "cache.sqlite"))


@pytest.fixture(autouse=True)
def _skip_live(request):
    if request.node.get_closest_marker("live") and os.environ.get("CITECHECK_LIVE") != "1":
        pytest.skip("live test: set CITECHECK_LIVE=1 to run")
