"""带来源映射的 LaTeX 源码串。

LaTeX 项目在解析前要经过多步改写：去注释、展开 \\input、去掉
filecontents、展开条件、改写 cite 别名、切出正文。每一步都会让字符
位置漂移。``Src`` 把改写后的文本和一张分段映射表放在一起：任何位置
都能追溯回 ``(文件序号, 文件内偏移)``，导出时据此把批注和修订写回
原始源文件。

映射段 ``Seg(cstart, file, fstart, exact)``：本段从组合文本的 cstart
开始；exact=True 表示逐字来自文件 fstart 起的同长度区间，False 表示
改写产生的文本（宏替换、别名），整段都指向 fstart 这一个位置。
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple


class Seg(NamedTuple):
    cstart: int
    file: int
    fstart: int
    exact: bool


@dataclass
class SourceFile:
    rel: str            # 相对项目根目录的路径（posix 分隔）
    text: str           # 原始全文，永不改写
    _line_starts: list[int] = field(default_factory=list, repr=False)

    def line_of(self, pos: int) -> int:
        """1 起的行号。"""
        if not self._line_starts:
            self._line_starts = [0] + [
                i + 1 for i, c in enumerate(self.text) if c == "\n"]
        return bisect_right(self._line_starts, pos)


class Src:
    """不可变的 (text, segs) 对。"""

    __slots__ = ("text", "segs", "_keys")

    def __init__(self, text: str, segs: list[Seg]):
        self.text = text
        self.segs = segs
        self._keys = [s.cstart for s in segs]

    @classmethod
    def of_file(cls, text: str, file: int) -> "Src":
        return cls(text, [Seg(0, file, 0, True)])

    @classmethod
    def literal(cls, text: str, file: int = -1, fpos: int = 0) -> "Src":
        return cls(text, [Seg(0, file, fpos, False)])

    def __len__(self) -> int:
        return len(self.text)

    def origin(self, pos: int) -> tuple[int, int, bool]:
        """组合文本位置 → (文件序号, 文件内偏移, 是否逐字)。"""
        if not self.segs:
            return -1, 0, False
        k = max(bisect_right(self._keys, pos) - 1, 0)
        s = self.segs[k]
        if s.exact:
            return s.file, s.fstart + (pos - s.cstart), True
        return s.file, s.fstart, False

    def slice(self, a: int, b: int) -> "Src":
        bld = Builder()
        bld.add(self, a, b)
        return bld.build()

    def edit(self, edits: list[tuple[int, int, "str | Src"]]) -> "Src":
        """按 (start, end, 替换) 改写；edits 不重叠。字符串替换锚定在被
        替换区间的起点，Src 替换保留它自己的映射。"""
        if not edits:
            return self
        bld = Builder()
        cur = 0
        for a, b, rep in sorted(edits, key=lambda e: e[0]):
            if a < cur:  # 重叠的编辑只取第一个
                continue
            bld.add(self, cur, a)
            if isinstance(rep, Src):
                bld.add(rep, 0, len(rep))
            elif rep:
                f, fp, _ = self.origin(a)
                bld.add_text(rep, f, fp)
            cur = b
        bld.add(self, cur, len(self.text))
        return bld.build()


class Builder:
    def __init__(self) -> None:
        self._parts: list[str] = []
        self._segs: list[Seg] = []
        self._len = 0

    def _push(self, seg: Seg) -> None:
        if self._segs:
            last = self._segs[-1]
            if last.cstart == seg.cstart:
                self._segs[-1] = seg
                return
            # 合并逐字连续的段
            if (last.exact and seg.exact and last.file == seg.file
                    and last.fstart + (seg.cstart - last.cstart) == seg.fstart):
                return
            if (not last.exact and not seg.exact and last.file == seg.file
                    and last.fstart == seg.fstart):
                return
        self._segs.append(seg)

    def add(self, src: Src, a: int, b: int) -> None:
        if b <= a:
            return
        k = max(bisect_right(src._keys, a) - 1, 0)
        segs = src.segs
        while k < len(segs) and segs[k].cstart < b:
            s = segs[k]
            nxt = segs[k + 1].cstart if k + 1 < len(segs) else len(src.text)
            lo, hi = max(a, s.cstart), min(b, nxt)
            if hi > lo:
                fstart = s.fstart + (lo - s.cstart) if s.exact else s.fstart
                self._push(Seg(self._len + (lo - a), s.file, fstart, s.exact))
            k += 1
        self._parts.append(src.text[a:b])
        self._len += b - a

    def add_text(self, text: str, file: int, fpos: int) -> None:
        if not text:
            return
        self._push(Seg(self._len, file, fpos, False))
        self._parts.append(text)
        self._len += len(text)

    def build(self) -> Src:
        return Src("".join(self._parts), list(self._segs))


@dataclass
class Project:
    """一个已读入的 LaTeX 项目：根目录 + 涉及到的源文件表。"""

    root: Path
    files: list[SourceFile] = field(default_factory=list)
    _index: dict[str, int] = field(default_factory=dict)

    def add(self, path: Path, text: str) -> int:
        rel = path.resolve().relative_to(self.root.resolve()).as_posix() \
            if _is_under(path, self.root) else path.name
        if rel in self._index:
            return self._index[rel]
        self._index[rel] = len(self.files)
        self.files.append(SourceFile(rel, text))
        return self._index[rel]


def _is_under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
