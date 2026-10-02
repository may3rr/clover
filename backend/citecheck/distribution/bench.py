"""领域对标数据加载。

默认读取 backend/benchmarks/arxiv_cs_cl.json（由
scripts/build_benchmark.py 生成）。
"""

from __future__ import annotations

import json
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parents[2] / "benchmarks" / "arxiv_cs_cl.json"


def load_benchmark(path: str | Path | None = None) -> dict:
    p = Path(path) if path else _DEFAULT
    return json.loads(p.read_text(encoding="utf-8"))
