"""Server endpoints backing the settings screen: prefs roundtrip, usage
aggregation shape, and the exported-comment identity derivation."""

import pytest
from fastapi.testclient import TestClient

from citecheck.server import app, TOKEN, _comment_identity


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from citecheck.config import get_settings

    monkeypatch.setenv("CITECHECK_CACHE", str(tmp_path / "t.sqlite"))
    get_settings.cache_clear()
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


H = {"Authorization": f"Bearer {TOKEN}"}


def test_prefs_roundtrip(client):
    r = client.get("/prefs", headers=H)
    assert r.status_code == 200
    assert r.json()["name"] == ""
    r = client.put("/prefs", headers=H, json={
        "name": "李明",
        "avatar": {"kind": "color", "color": "teal", "image": None},
        "comment_author": "王老师",
    })
    assert r.status_code == 200
    got = client.get("/prefs", headers=H).json()
    assert got["name"] == "李明"
    assert got["avatar"]["color"] == "teal"
    assert got["comment_author"] == "王老师"


def test_prefs_rejects_oversized_avatar(client):
    big = "data:image/png;base64," + "x" * 2_000_001
    r = client.put("/prefs", headers=H, json={
        "avatar": {"kind": "image", "color": "blue", "image": big}})
    assert r.status_code == 400


def test_comment_identity_derivation():
    # single-word name -> first two chars; multi-word -> first letters;
    # short names stay whole; everything falls back to Clover
    assert _comment_identity({"name": "Jackie"}) == ("Jackie", "JA")
    assert _comment_identity({"name": "Li Ming Yuan"}) == (
        "Li Ming Yuan", "LM")
    assert _comment_identity({"name": "李明"}) == ("李明", "李明")
    assert _comment_identity({}) == ("Clover", "CL")
    assert _comment_identity(
        {"name": "李明", "comment_author": "王老师",
         "comment_initials": "WS"}) == ("王老师", "WS")


def test_usage_shape_and_config(client):
    r = client.get("/usage", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"by_doc", "by_provider", "by_day", "totals"}

    r = client.get("/config", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert "base_url" in body and "models" in body
    assert "judge" in body["models"]
    # the api key is never echoed back
    assert "api_key" not in body and "dashscope_api_key" not in body


def test_put_config_returns_settings(tmp_path, monkeypatch):
    """PUT /config writes config.toml + .env and answers with the new
    settings as JSON (regression: it once returned an un-awaited coroutine,
    which crashed FastAPI's encoder after the files were already written)."""
    import citecheck.config as cfgmod
    from citecheck.config import get_settings

    cfg = tmp_path / "config.toml"
    cfg.write_text(cfgmod._CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8"),
                   encoding="utf-8")
    monkeypatch.setattr(cfgmod, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(cfgmod, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("CITECHECK_CACHE", str(tmp_path / "t.sqlite"))
    get_settings.cache_clear()
    try:
        r = TestClient(app).put("/config", headers=H, json={
            "base_url": "https://example.test/compatible-mode/v1",
            "dashscope_api_key": "sk-test",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["base_url"] == "https://example.test/compatible-mode/v1"
        assert body["has_api_key"] is True
        assert "DASHSCOPE_API_KEY=sk-test" in (tmp_path / ".env").read_text()
    finally:
        get_settings.cache_clear()
