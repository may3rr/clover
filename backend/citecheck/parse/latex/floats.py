"""LaTeX 浮动体与表格：切出表格单元格、题注与插图路径。

figure / table 一类环境整体不进正文流；这里把其中可读的部分抢救成
块：``\\caption`` 成为题注段落，``tabular`` 系列环境逐格成为单元格
段落（带行列坐标），``\\includegraphics`` 的路径挂到其后最近的题注上
（没有题注时单独成一个只有图的段落）。块只记录正文中的区间，渲染与
位置映射照常走 render_mapped。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import tex

TABULAR_ENVS = {"tabular", "tabular*", "tabularx", "tabulary", "longtable",
                "longtable*", "tabu", "supertabular", "xtabular"}
# 第一个必选参数是宽度、第二个才是列格式的环境
_WIDTH_FIRST = {"tabular*", "tabularx", "tabulary", "tabu"}

_EVENT_RE = re.compile(
    r"\\(?:begin\s*\{(" + "|".join(re.escape(e) for e in TABULAR_ENVS)
    + r")\}|(caption|includegraphics)(?![a-zA-Z])\*?)")
_RULE_RE = re.compile(
    r"(?:\s|\\(?:hline|toprule|midrule|bottomrule|cline|cmidrule|"
    r"addlinespace|specialrule|hhline|rowcolor|morecmidrules|noalign|"
    r"endfirsthead|endhead|endfoot|endlastfoot|tabucline|bottomrule)"
    r"(?![a-zA-Z])(?:\s*\([^)]*\))?(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})*)+")
_SPAN_RE = re.compile(r"\\(multicolumn|multirow)(?![a-zA-Z])")


@dataclass
class FloatPart:
    kind: str                       # cell | caption | figure
    ranges: list[tuple[int, int]] = field(default_factory=list)
    at: int = 0
    cell: tuple[str, int, int, int, bool] | None = None  # 表, 行, 列, 跨列, 表头
    images: list[str] = field(default_factory=list)


def _opt_args(src: str, i: int) -> int:
    i = tex._skip_ws(src, i)
    while i < len(src) and src[i] == "[":
        r = tex._read_balanced(src, i, "[", "]")
        if r is None:
            break
        i = tex._skip_ws(src, r[1])
    return i


def _arg(src: str, i: int) -> tuple[int, int, int] | None:
    """跳过可选参数后读一个 {..}：返回 (内容起, 内容止, 下一位置)。"""
    i = _opt_args(src, i)
    r = tex._read_balanced(src, i, "{", "}")
    if r is None:
        return None
    return i + 1, r[1] - 1, r[1]


def _split_rows(src: str, a: int, b: int) -> list[list[tuple[int, int]]]:
    """表体按顶层的 ``\\\\`` 分行、``&`` 分格（花括号与嵌套环境内的不算）。"""
    rows: list[list[tuple[int, int]]] = []
    cells: list[tuple[int, int]] = []
    start, depth, env, j = a, 0, 0, a
    while j < b:
        c = src[j]
        if c == "\\":
            nxt = src[j + 1] if j + 1 < b else ""
            if nxt == "\\":
                if depth == 0 and env == 0:
                    cells.append((start, j))
                    rows.append(cells)
                    cells = []
                    k = j + 2
                    kk = tex._skip_ws(src, k)
                    if kk < b and src[kk] == "[":  # \\[2pt]
                        r = tex._read_balanced(src, kk, "[", "]")
                        k = r[1] if r else k
                    start = j = k
                    continue
                j += 2
                continue
            if nxt.isalpha():
                k = j + 1
                while k < b and src[k].isalpha():
                    k += 1
                name = src[j + 1:k]
                if name == "begin":
                    env += 1
                elif name == "end":
                    env = max(env - 1, 0)
                elif name == "tabularnewline" and depth == 0 and env == 0:
                    cells.append((start, j))
                    rows.append(cells)
                    cells = []
                    start = k
                j = k
                continue
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(depth - 1, 0)
        elif c == "&" and depth == 0 and env == 0:
            cells.append((start, j))
            start = j + 1
        j += 1
    cells.append((start, b))
    rows.append(cells)
    return rows


def _cell_content(src: str, a: int, b: int) -> tuple[int, int, int]:
    """剥掉 \\multicolumn / \\multirow 外壳：返回 (起, 止, 跨列数)。"""
    span = 1
    while True:
        k = tex._skip_ws(src, a)
        m = _SPAN_RE.match(src, k)
        if not m or m.end() > b:
            break
        if m.group(1) == "multicolumn":
            n = _arg(src, m.end())
            spec = _arg(src, n[2]) if n else None
            body = _arg(src, spec[2]) if spec else None
            if not body or body[2] > b:
                break
            try:
                span = max(int(src[n[0]:n[1]].strip()), 1)
            except ValueError:
                span = 1
        else:  # \multirow[..]{rows}[..]{width}[..]{text}
            n = _arg(src, m.end())
            w = _arg(src, n[2]) if n else None
            body = _arg(src, w[2]) if w else None
            if not body or body[2] > b:
                break
        a, b = body[0], body[1]
    return a, b, span


def _table(src: str, a: int, b: int, tid: str) -> list[FloatPart]:
    parts: list[FloatPart] = []
    rows = _split_rows(src, a, b)
    header_end, header_set = 1, False
    out_rows: list[list[tuple[int, int, int]]] = []
    captions: list[FloatPart] = []
    for cells in rows:
        # 行首的横线类命令剥掉；\midrule 之前的行算表头
        first_a, first_b = cells[0]
        m = _RULE_RE.match(src, first_a, first_b)
        if m and m.end() > first_a:
            rule = src[first_a:m.end()]
            if not header_set and out_rows and len(out_rows) <= 3 and (
                    "midrule" in rule or "hline" in rule):
                header_end, header_set = len(out_rows), True
            cells = [(m.end(), first_b)] + cells[1:]
        k = tex._skip_ws(src, cells[0][0])
        cm = re.match(r"\\caption(?![a-zA-Z])\*?", src[k:cells[0][1]])
        if cm:  # longtable 的题注写在表体里
            arg = _arg(src, k + cm.end())
            if arg and arg[2] <= cells[0][1]:
                captions.append(FloatPart("caption", [(arg[0], arg[1])],
                                          at=arg[0]))
            continue
        row: list[tuple[int, int, int]] = []
        for ca, cb in cells:
            row.append(_cell_content(src, ca, cb))
        if any(src[x:y].strip() for x, y, _ in row):
            out_rows.append(row)
    parts.extend(captions)
    for r, row in enumerate(out_rows):
        col = 0
        for x, y, span in row:
            if src[x:y].strip():
                parts.append(FloatPart(
                    "cell", [(x, y)], at=x,
                    cell=(tid, r, col, span, r < header_end)))
            col += span
    return parts


def scan_float(src: str, a: int, b: int, next_table: int) -> tuple[list[FloatPart], int]:
    """扫描 [a, b) 中的浮动体（或独立的 tabular）。返回 (块, 新的表序号)。"""
    parts: list[FloatPart] = []
    pending: list[str] = []
    last_caption: FloatPart | None = None
    i = a
    while True:
        m = _EVENT_RE.search(src, i, b)
        if not m:
            break
        if m.group(1):  # tabular 系列
            env = m.group(1)
            end = _end_of(src, m.end(), env, b)
            k = m.end()
            if env in _WIDTH_FIRST:
                w = _arg(src, k)
                k = w[2] if w else k
            spec = _arg(src, k)
            body_a = spec[2] if spec else k
            tid = f"t{next_table}"
            next_table += 1
            for p in _table(src, body_a, end[0], tid):
                parts.append(p)
                if p.kind == "caption":
                    last_caption = p
            i = end[1]
            continue
        arg = _arg(src, m.end())
        if arg is None:
            i = m.end()
            continue
        if m.group(2) == "includegraphics":
            path = src[arg[0]:arg[1]].strip()
            if path:
                pending.append(path)
        else:
            last_caption = FloatPart("caption", [(arg[0], arg[1])], at=arg[0],
                                     images=pending)
            parts.append(last_caption)
            pending = []
        i = arg[2]
    if pending:
        if last_caption is not None:
            last_caption.images.extend(pending)
        else:
            parts.append(FloatPart("figure", at=a, images=pending))
    return parts, next_table


def _end_of(src: str, start: int, env: str, limit: int) -> tuple[int, int]:
    """\\end{env} 的 (起, 止)；嵌套同名计深。"""
    tok = re.compile(r"\\(begin|end)\s*\{" + re.escape(env) + r"\}")
    depth = 1
    for m in tok.finditer(src, start, limit):
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return m.start(), m.end()
    return limit, limit
