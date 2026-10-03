import threading
from pathlib import Path

from citecheck.cache import Cache, make_key


def test_make_key_stable():
    k1 = make_key("qwen-plus", "prompt text")
    k2 = make_key("qwen-plus", "prompt text")
    assert k1 == k2 and len(k1) == 64
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
