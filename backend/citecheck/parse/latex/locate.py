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


    def snippet(self, pid: str, start: int, end: int
                ) -> tuple[str, tuple[int, int] | None] | None:
        """锚点覆盖的源码行（至多 4 行，每行截到 240 字），以及锚点在
        片段里的区间（两端都逐字映射时才有）。"""
        a = self.lmap.locate(pid, start)
        if a is None:
            return None
        f = self.file(a[0])
        if f is None:
            return None
        b = self.lmap.locate(pid, max(end - 1, start))
        same = b is not None and b[0] == a[0] and b[1] >= a[1]
        ls = f.text.rfind("\n", 0, a[1]) + 1
        last = b[1] if same else a[1]
        le = f.text.find("\n", last)
        le = len(f.text) if le < 0 else le
        lines = f.text[ls:le].split("\n")[:4]
        text = "\n".join(ln[:240] for ln in lines)
        hl = None
        if same:
            s0 = a[1] - ls
            # a non-verbatim end sits on a command (a rendered \cite, a
            # macro): extend over the whole command and its arguments
            e_abs = b[1] + 1 if b[2] else _command_end(f.text, b[1])
            e0 = e_abs - ls
            if 0 <= s0 < e0 <= len(text):
                hl = (s0, e0)
        return text, hl


def _command_end(text: str, pos: int) -> int:
    """End of the LaTeX command starting at pos: name, then any [..] and
    {..} arguments. A position that isn't a command covers one char."""
    from .tex import _CMD_RE, _read_balanced, _skip_ws
    m = _CMD_RE.match(text, pos) if pos < len(text) and text[pos] == "\\" else None
    if m is None:
        return pos + 1
    k = m.end()
    while True:
        j = _skip_ws(text, k)
        if j < len(text) and text[j] in "[{":
            r = _read_balanced(text, j, text[j], "]" if text[j] == "[" else "}")
            if r is None:
                break
            k = r[1]
            continue
        break
    return k


def annotate_locations(lmap: LatexMap, anchors) -> None:
    """为每个 Anchor 填上 loc 与源码片段（就地修改）。"""
    loc = Locator(lmap)
    for a in anchors:
        if a is None:
            continue
        a.loc = loc.loc(a.paragraph_id, a.start)
        sn = loc.snippet(a.paragraph_id, a.start, a.end)
        if sn is not None:
            a.snippet, a.snippet_hl = sn
