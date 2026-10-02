"""Route policy: which backend serves a task (AGENTS: 端云路由).

``extract`` prefers the local mlx model and falls back to cloud; every
other task is cloud-only. ``llm.local.enabled = false`` forces cloud.
"""

from __future__ import annotations

from ..config import Settings


def route_order(task: str, settings: Settings) -> list[str]:
    """Ordered list of backends to try for a task."""
    if task == "extract" and settings.llm.local.enabled:
        return ["local", "cloud"]
    return ["cloud"]
