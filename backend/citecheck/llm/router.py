"""Route policy: which backend serves a task (AGENTS: 端云路由).

``llm.local.tasks`` lists the tasks that prefer the local model and fall
back to cloud; every other task is cloud-only. ``llm.local.enabled = false``
forces cloud.
"""

from __future__ import annotations

from ..config import Settings


def route_order(task: str, settings: Settings) -> list[str]:
    """Ordered list of backends to try for a task."""
    local = settings.llm.local
    if local.enabled and task in local.tasks:
        return ["local", "cloud"]
    return ["cloud"]
