"""把报告锚点（段落 + 段内位置）换算成 LaTeX 源码的 文件:行号。"""

from __future__ import annotations

from pathlib import Path

from ..parser import LatexMap
from .source import SourceFile
from .tex import read_text


class Locator:
    def __init__(self, lmap: LatexMap):
        self.lmap = lmap
        self._files: dict[str, SourceFile | None] = {}

    def file(self, rel: str) -> SourceFile | None:
        if rel not in self._files:
            p = Path(self.lmap.root) / rel
            try:
                self._files[rel] = SourceFile(rel, read_text(p))
            except OSError:
                self._files[rel] = None
        return self._files[rel]

    def offset(self, pid: str, pos: int) -> tuple[str, int, bool] | None:
        return self.lmap.locate(pid, pos)

    def loc(self, pid: str, pos: int) -> str | None:
        hit = self.lmap.locate(pid, pos)
        if hit is None:
            return None
        rel, fpos, _ = hit
        f = self.file(rel)
        if f is None:
            return rel
        return f"{rel}:{f.line_of(fpos)}"


def annotate_locations(lmap: LatexMap, anchors) -> None:
    """为每个 Anchor 填上 loc（就地修改）。"""
    loc = Locator(lmap)
    for a in anchors:
        if a is not None:
            a.loc = loc.loc(a.paragraph_id, a.start)
