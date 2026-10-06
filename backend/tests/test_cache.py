import threading
from pathlib import Path

from citecheck.cache import Cache, make_key


def test_make_key_stable():
    k1 = make_key("qwen-plus", "prompt text")
    k2 = make_key("qwen-plus", "prompt text")
    # readable prefix + sha256 digest — the prefix drives cache TTLs
    assert k1 == k2
    prefix, _, digest = k1.partition("|")
    assert prefix == "qwen-plus" and len(digest) == 64
    assert make_key("a", "b") != make_key("ab")


def test_get_set(tmp_path):
    with Cache(tmp_path / "c.sqlite") as cache:
        assert cache.get("missing") is None
        cache.set("k1", {"a": 1, "b": "中文"})
        assert cache.get("k1") == {"a": 1, "b": "中文"}
        cache.set("k1", [1, 2, 3])
        assert cache.get("k1") == [1, 2, 3]


def test_persists_across_instances(tmp_path):
    p = tmp_path / "c.sqlite"
    with Cache(p) as c1:
        c1.set("k", "v")
    with Cache(p) as c2:
        assert c2.get("k") == "v"


def test_thread_safe(tmp_path):
    with Cache(tmp_path / "c.sqlite") as cache:
        def worker(i: int) -> None:
            for j in range(20):
                cache.set(f"k{i}-{j}", j)
                assert cache.get(f"k{i}-{j}") == j

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert cache.get("k7-19") == 19


def test_creates_parent_dirs(tmp_path):
    p = tmp_path / "deep" / "nested" / "c.sqlite"
    with Cache(p) as cache:
        cache.set("x", 1)
    assert Path(p).exists()


# ----------------------------------------------------------- TTL

def test_retrieval_key_expires_and_is_deleted(tmp_path, monkeypatch):
    """Retrieval entries (crossref|/openalex|/s2|/arxiv| prefixes) live
    30 days; a stale hit reads as a miss and is deleted."""
    import time as time_mod

    with Cache(tmp_path / "c.sqlite") as cache:
        key = make_key("crossref", "work", "10.x/abc")
        cache.set(key, {"message": {}})
        stale = int(time_mod.time()) - 31 * 86400
        cache._conn.execute(
            "UPDATE kv SET created_at = ? WHERE key = ?", (stale, key))
        cache._conn.commit()
        assert cache.get(key) is None
        row = cache._conn.execute(
            "SELECT 1 FROM kv WHERE key = ?", (key,)).fetchone()
        assert row is None  # expired entry was removed


def test_llm_key_never_expires(tmp_path):
    """LLM verdicts have no TTL — they are invalidated deliberately via
    cache_version, not by age."""
    import time as time_mod

    with Cache(tmp_path / "c.sqlite") as cache:
        key = make_key("qwen-plus", "prompt text")
        cache.set(key, {"label": "ok"})
        stale = int(time_mod.time()) - 400 * 86400
        cache._conn.execute(
            "UPDATE kv SET created_at = ? WHERE key = ?", (stale, key))
        cache._conn.commit()
        assert cache.get(key) == {"label": "ok"}


def test_created_at_migrated_for_existing_db(tmp_path):
    """A kv table from before the TTL migration opens cleanly: existing
    rows are backfilled with 'now' and keep hitting."""
    import sqlite3

    p = tmp_path / "old.sqlite"
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO kv VALUES ('k', '{\"a\": 1}')")
    conn.commit()
    conn.close()
    with Cache(p) as cache:
        assert cache.get("k") == {"a": 1}
        cache.set("k2", 2)  # new writes carry a timestamp too
        assert cache.get("k2") == 2


def test_usage_log_aggregates(tmp_path):
    with Cache(tmp_path / "c.sqlite") as c:
        c.record_usage("dashscope", "qwen3.8-flash", "judge", 100, 20)
        c.record_usage("dashscope", "qwen3.8-flash", "judge", 50, 10,
                       cached=True)
        c.record_usage("dashscope", "qwen3.8-max", "review", 800, 200)
        c.record_usage("mlx-local", "Qwen3.5-4B", "extract", 300, 40)
        rows = c.usage_summary()
    assert len(rows) == 3
    by_model = {r["model"]: r for r in rows}
    assert by_model["qwen3.8-flash"]["calls"] == 2
    assert by_model["qwen3.8-flash"]["cached_calls"] == 1
    assert by_model["qwen3.8-flash"]["prompt"] == 150
    assert by_model["qwen3.8-max"]["provider"] == "dashscope"
    assert by_model["Qwen3.5-4B"]["provider"] == "mlx-local"


def _save(cache: Cache, rid: str, **kw) -> None:
    cache.save_report(
        rid,
        kw.get("filename", f"{rid}.docx"),
        kw.get("title", f"Title {rid}"),
        kw.get("src_path", f"/tmp/{rid}.docx"),
        kw.get("benchmark", "arxiv_cs_cl"),
        kw.get("severity_counts", {"high": 2, "medium": 3, "low": 1}),
        kw.get("report_json", '{"document": {"filename": "x.docx"}}'),
    )


def test_reports_roundtrip(tmp_path):
    with Cache(tmp_path / "c.sqlite") as cache:
        _save(cache, "r1")
        _save(cache, "r2")
        listing = cache.list_reports()
        assert [r["id"] for r in listing] == ["r2", "r1"]  # newest first
        assert listing[0]["n_high"] == 2
        assert "report_json" not in listing[0]  # list stays light
        row = cache.get_report("r1")
        assert row["src_path"] == "/tmp/r1.docx"
        assert '"document"' in row["report_json"]
        assert cache.get_report("nope") is None


def test_reports_delete(tmp_path):
    with Cache(tmp_path / "c.sqlite") as cache:
        _save(cache, "r1")
        assert cache.delete_report("r1") is True
        assert cache.delete_report("r1") is False
        assert cache.list_reports() == []


def test_reports_same_file_twice_lists_both(tmp_path):
    # dropping the same docx again is a new job id → two parallel entries
    with Cache(tmp_path / "c.sqlite") as cache:
        _save(cache, "jobA", filename="paper.docx")
        _save(cache, "jobB", filename="paper.docx")
        assert len(cache.list_reports()) == 2
