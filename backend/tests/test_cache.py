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
