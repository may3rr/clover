"""T1 smoke: 32 concurrent client.chat_json("extract") on the local 8B.

Uses CITECHECK_HOME=C:\\clover-data\\smoke-home (local openvino + batching).
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("CITECHECK_HOME", r"C:\clover-data\smoke-home")
CLOVER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CLOVER / "backend"))

from citecheck.llm.client import chat_json  # noqa: E402
from citecheck.support.claims import _ClaimsOut, _PROMPT  # noqa: E402


async def main() -> None:
    messages = [
        {"role": "user", "content": _PROMPT.format(
            sentence=(f"We adopt Faster R-CNN ⟦m1⟧, which runs at 5 frames per second on a GPU, "
                      f"as our detection baseline. Case {i}."))}
        for i in range(32)
    ]
    t0 = time.perf_counter()
    results = await asyncio.gather(*[
        chat_json("extract", [m], _ClaimsOut) for m in messages])
    total = time.perf_counter() - t0
    ok = sum(1 for r in results if r.value is not None)
    routes = {}
    for r in results:
        routes[r.route] = routes.get(r.route, 0) + 1
    print(f"total {total:.2f}s, ok {ok}/32, routes {routes}, "
          f"avg {total/32:.2f}s/request", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
