"""LaTeX 源码 → 纯文本渲染。

render() 把一段 latex 源码渲染成段落文本：排版命令丢弃、文本命令保留
参数、数学内容扁平化。\\cite 系列命令本身不渲染，交给调用方的
cite_render(name, keys) 生成替换文本（数字编号或作者-年份样式），
锚点位置记入 RenderedMarker，供下游构建 CitationMarker。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .source import Builder, Project, Src

# ---------------------------------------------------------------- cite 命令

# newcite / shortcite: ACL 模板（acl_natbib）自带的引用命令
_TEXTUAL = {"citet", "textcite", "citealt", "newcite", "citeasnoun"}
_AUTHOR_ONLY = {"citeauthor", "citeauthors"}
_YEAR_ONLY = {"citeyear", "citeyearpar", "shortcite"}
_PAREN = {
    "cite", "citep", "citealp", "parencite", "autocite", "footcite",
    "smartcite", "supercite", "notecite", "pnotecite", "citenum",
}
_MULTI = {
    "cites", "parencites", "textcites", "citets", "citeps",
    "footcites", "autocites", "smartcites", "supercites",
}


def cite_kind(name: str) -> str | None:
    """把命令名归类为 cite 类型；不是引用命令返回 None。

    白名单制：\\mycite、\\citefield、\\citetrackerfalse 这类名字里
    碰巧含 cite 的命令不算引用。"""
    if name in _AUTHOR_ONLY:
        return "author"
    if name in _YEAR_ONLY:
        return "year"
    if name in _TEXTUAL:
        return "textual"
    if name in _PAREN or name in _MULTI:
        return "paren"
    return None


# ------------------------------------------------------- 命令处理规则

# 丢弃命令本体及其后一个 {...} 参数
_DROP_ARG = {
    "label", "ref", "eqref", "pageref", "autoref", "cref", "crefrange",
    "cpageref", "index", "gls", "glsadd", "nocite", "footnotemark",
    "hypertarget", "phantom", "hphantom", "vphantom", "vspace", "hspace",
    "addcontentsline", "markboth", "markright", "thanks", "institution",
    "affiliation", "email", "author", "date", "title", "keywords",
    "includegraphics", "bibliography", "bibliographystyle",
    "addbibresource", "documentclass", "usepackage", "begin", "end",
}

# 丢弃命令本体及第一个参数，第二个参数文本照常流出（href、textcolor 等）
_DROP_FIRST_ARG = {"href", "textcolor", "colorlink", "resizebox", "scalebox",
                   "rotatebox", "colorbox"}

# 丢弃命令及其后 N 个 {...} 参数（中间可夹 [...]）：设置类命令，参数
# 不是正文
_DROP_N_ARGS = {
    "setlength": 2, "addtolength": 2, "setcounter": 2, "addtocounter": 2,
    "definecolor": 3, "hypersetup": 1, "captionsetup": 1, "newcommand": 2,
    "renewcommand": 2, "providecommand": 2, "newenvironment": 3,
    "renewenvironment": 3, "newtheorem": 2, "setcitestyle": 1,
    "graphicspath": 1, "pagestyle": 1, "thispagestyle": 1, "fontsize": 2,
    "selectfont": 0, "titlespacing": 4, "newif": 0, "vskip": 0, "hskip": 0,
}
# TeX 赋值：\looseness=-1、\parskip=3pt、\vskip 2pt
_ASSIGN_RE = re.compile(
    r"\s*=?\s*-?\s*(?:\d+\.?\d*|\.\d+)\s*(?:pt|em|ex|cm|mm|in|bp|sp|mu|"
    r"\\[a-zA-Z]+)?(?:\s*(?:plus|minus)\s*-?\d*\.?\d*\s*(?:pt|em|ex|fil+)?)*")

# 单个字符命令 / 符号命令 → 字面字符
_SYMBOLS = {
    "&": "&", "%": "%", "$": "$", "#": "#", "_": "_", "{": "{",
    "}": "}", "i": "ı", "j": "ȷ", "o": "ø", "O": "Ø", "l": "ł",
    "L": "Ł", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
    "aa": "å", "AA": "Å", "ss": "ß", "dag": "†", "ddag": "‡",
    "S": "§", "P": "¶", "copyright": "©", "ldots": "…", "dots": "…",
    "textemdash": "—", "textendash": "–", "textasciitilde": "~",
    "textbackslash": "\\", "LaTeX": "LaTeX", "TeX": "TeX",
    "slash": "/", "textquotedblleft": '"', "textquotedblright": '"',
    "textquoteleft": "'", "textquoteright": "'",
}

# 空白 / 间距命令 → 空格（\\! \\- 这类收缩命令映射为空串）
_SPACERS = {
    " ": " ", ",": " ", ";": " ", ":": " ", "/": " ", "quad": " ",
    "qquad": " ", "enspace": " ", "thinspace": " ", "medspace": " ",
    "thickspace": " ", "par": " ", "newline": " ", "linebreak": " ",
    "pagebreak": " ", "noindent": "", "indent": "", "!": "",
    "-": "", "bigskip": " ", "medskip": " ", "smallskip": " ",
    "centering": "", "raggedright": "", "raggedleft": "",
}

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "vartheta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "varpi": "π", "rho": "ρ", "varrho": "ρ", "sigma": "σ",
    "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
    "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "times": "×", "cdot": "·", "pm": "±", "mp": "∓",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠",
    "ne": "≠", "approx": "≈", "sim": "∼", "propto": "∝",
    "infty": "∞", "partial": "∂", "nabla": "∇", "forall": "∀",
    "exists": "∃", "in": "∈", "notin": "∉", "subset": "⊂",
    "supset": "⊃", "subseteq": "⊆", "supseteq": "⊇", "cup": "∪",
    "cap": "∩", "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮",
    "rightarrow": "→", "to": "→", "leftarrow": "←", "Rightarrow": "⇒",
    "Leftarrow": "⇐", "leftrightarrow": "↔", "mapsto": "↦",
    "ldots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    "degree": "°", "prime": "′", "hbar": "ħ", "ell": "ℓ",
    "emptyset": "∅", "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ",
}

# 变音命令 → 组合变音符（NFC 归一化后落在前一个字符上）
_ACCENTS = {
    "'": "́", "`": "̀", '"': "̈", "^": "̂",
    "~": "̃", "=": "̄", ".": "̇", "u": "̆",
    "v": "̌", "H": "̋", "c": "̧", "k": "̨",
    "b": "̱", "d": "̣", "r": "̊", "t": "͡",
}

_CMD_RE = re.compile(r"\\([a-zA-Z]+\*?|.)", re.S)


@dataclass
class RenderedMarker:
    start: int
    end: int
    name: str           # 归一化后的命令名（小写、去 *）
    keys: list[str] = field(default_factory=list)


@dataclass
class Macro:
    """\\newcommand / \\def 定义的文本宏。"""
    nargs: int
    default: str | None  # 第一个参数可选时的默认值
    body: str


# 渲染位置映射：(渲染文本位置, 源码位置, 是否逐字)。逐字段内渲染位置
# 每 +1，源码位置也 +1；非逐字段整段指向同一个源码位置。
PosRun = tuple[int, int, bool]


def _skip_ws(src: str, i: int) -> int:
    while i < len(src) and src[i] in " \t\n":
        i += 1
    return i


def _read_balanced(src: str, i: int, open_c: str, close_c: str) -> tuple[str, int] | None:
    """src[i] == open_c → (inner, next_i)；未闭合返回 None。"""
    if i >= len(src) or src[i] != open_c:
        return None
    depth, j = 0, i
    while j < len(src):
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return src[i + 1 : j], j + 1
        j += 1
    return None


def _read_cite_args(src: str, i: int, multi: bool) -> tuple[list[str], int]:
    """读取 \\cite 的参数：可选 [...] 若干 + {key1,key2}；multi 命令
    （\\cites 系列）继续读后续的 {..} 组。"""
    keys: list[str] = []
    while True:
        j = _skip_ws(src, i)
        while j < len(src) and src[j] == "[":
            r = _read_balanced(src, j, "[", "]")
            if r is None:
                return keys, i
            j = _skip_ws(src, r[1])
        if j < len(src) and src[j] == "{":
            r = _read_balanced(src, j, "{", "}")
            if r is None:
                return keys, i
            keys += [k.strip() for k in r[0].split(",") if k.strip()]
            i = r[1]
            if not multi:
                break
        else:
            break
    return keys, i


def _read_macro_args(src: str, i: int, m: Macro) -> tuple[list[str], int]:
    """按宏定义读取实参：可选首参 [..]，其余 {..} 或单个记号。"""
    args: list[str] = []
    n = m.nargs
    if m.default is not None and n:
        j = _skip_ws(src, i)
        r = _read_balanced(src, j, "[", "]") if j < len(src) and src[j] == "[" else None
        if r:
            args.append(r[0])
            i = r[1]
        else:
            args.append(m.default)
        n -= 1
    for _ in range(n):
        j = _skip_ws(src, i)
        if j >= len(src):
            args.append("")
            continue
        r = _read_balanced(src, j, "{", "}")
        if r:
            args.append(r[0])
            i = r[1]
            continue
        cm = _CMD_RE.match(src, j)
        if src[j] == "\\" and cm:
            args.append(cm.group(0))
            i = cm.end()
        else:
            args.append(src[j])
            i = j + 1
    return args, i


def _substitute(body: str, args: list[str]) -> str:
    def repl(mm: re.Match) -> str:
        k = int(mm.group(1)) - 1
        return args[k] if 0 <= k < len(args) else ""
    return re.sub(r"#([1-9])", repl, body)


def _render_math(s: str, macros: dict[str, Macro] | None = None) -> str:
    """数学内容扁平化：\\frac{a}{b}→a/b，希腊字母/符号换 unicode，
    其余命令名丢弃、分组括号去掉。零参数宏先展开（最多三轮）。"""
    if macros:
        for _ in range(3):
            changed = False

            def mrepl(mm: re.Match) -> str:
                nonlocal changed
                mac = macros.get(mm.group(1))
                if mac is None or mac.nargs:
                    return mm.group(0)
                changed = True
                return mac.body
            s = re.sub(r"\\([a-zA-Z]+)(?![a-zA-Z])", mrepl, s)
            if not changed:
                break
    s = re.sub(
        r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1/\2", s
    )
    s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", s)
    # \mathrm{x} \text{x} \operatorname{x}：保留参数文本
    s = re.sub(r"\\(?:mathrm|mathit|mathbf|mathsf|mathtt|mathcal|mathbb|"
               r"text|textrm|textit|textbf|operatorname|boldsymbol|bm)\s*",
               "", s)

    def repl(m: re.Match) -> str:
        name = m.group(1)
        if len(name) == 1 and not name.isalpha():
            return _SYMBOLS.get(name, "") if name != " " else " "
        base = name.rstrip("*")
        return _GREEK.get(base) or _SYMBOLS.get(base) or _SPACERS.get(base, "")

    s = _CMD_RE.sub(repl, s)
    return s.replace("{", "").replace("}", "")


_MAX_DEPTH = 12
_MAX_EXPANSION = 20000


def render(
    src: str,
    cite_render: Callable[[str, list[str]], str] | None = None,
    macros: dict[str, Macro] | None = None,
) -> tuple[str, list[RenderedMarker]]:
    """渲染 latex 源码为纯文本；返回 (text, markers)。

    cite_render(name, keys) 给出 \\cite 命令的替换文本；为 None 时引用
    命令不产出文本也不记 marker。
    """
    text, marks, _, _ = render_mapped(src, cite_render, macros)
    return text, marks


def render_mapped(
    src: str,
    cite_render: Callable[[str, list[str]], str] | None = None,
    macros: dict[str, Macro] | None = None,
    _depth: int = 0,
) -> tuple[str, list[RenderedMarker], list[PosRun],
           list[tuple[int, int, str]]]:
    """render() 加位置映射：第三个返回值把渲染文本的每个位置映射回
    src 中的位置（见 PosRun）；第四个是行内公式 (起, 止, LaTeX 源码)，
    坐标是渲染文本的位置，阅读区据此把公式排成上下标。"""
    out: list[str] = []
    # 与 out 中每个字符平行：源码位置与是否逐字
    o_src: list[int] = []
    o_exact: list[bool] = []
    marks: list[RenderedMarker] = []
    # inline math: (start, end, latex source) in pre-collapse coordinates
    maths: list[tuple[int, int, str]] = []
    i, n = 0, len(src)
    pos = 0
    macros = macros or {}

    def emit_math(body: str, at: int) -> None:
        start = pos
        emit(_render_math(body, macros), at)
        if pos > start:
            maths.append((start, pos, body))

    def emit(s: str, at: int, exact: bool = False) -> None:
        nonlocal pos
        if not s:
            return
        out.append(s)
        pos += len(s)
        if exact:
            o_src.extend(range(at, at + len(s)))
            o_exact.extend([True] * len(s))
        else:
            o_src.extend([at] * len(s))
            o_exact.extend([False] * len(s))

    while i < n:
        ch = src[i]

        # ---- 引号与连字符 -------------------------------------------
        if ch in "`'-":
            hit = None
            for lit, rep in (("``", "“"), ("''", "”"), ("---", "—"),
                             ("--", "–"), ("`", "‘"), ("'", "’")):
                if src.startswith(lit, i):
                    hit = (lit, rep)
                    break
            if hit is not None:
                emit(hit[1], i)
                i += len(hit[0])
                continue

        # ---- 数学 ----------------------------------------------------
        if ch == "$":
            if src.startswith("$$", i):
                j = src.find("$$", i + 2)
                j = n - 2 if j < 0 else j
                emit_math(src[i + 2 : j], i)
                i = j + 2
            else:
                j = i + 1
                while j < n:
                    if src[j] == "$" and src[j - 1] != "\\":
                        break
                    j += 1
                emit_math(src[i + 1 : min(j, n)], i)
                i = j + 1
            continue

        # ---- 分组与特殊字符 ------------------------------------------
        if ch in "{}":
            i += 1
            continue
        if ch == "~" or ch == "&":
            emit(" ", i)
            i += 1
            continue

        # ---- 命令 ----------------------------------------------------
        if ch == "\\":
            m = _CMD_RE.match(src, i)
            if not m:
                i += 1
                continue
            name = m.group(1)
            j = m.end()

            # 单字符控制符号：\$ \% \\ \( \[ \' \` ...
            if len(name) == 1 and not name.isalpha():
                if name in "([":
                    closer = "\\)" if name == "(" else "\\]"
                    k = src.find(closer, j)
                    k = n if k < 0 else k
                    emit_math(src[j:k], i)
                    i = k + (2 if k < n else 0)
                elif name == "\\":
                    emit(" ", i)
                    i = j
                elif name in _ACCENTS:
                    inner, j2 = _accent_arg(src, j)
                    emit(unicodedata.normalize("NFC", inner + _ACCENTS[name]), i)
                    i = j2
                elif name in _SPACERS:
                    emit(_SPACERS[name], i)
                    i = j
                else:
                    emit(_SYMBOLS.get(name, ""), i)
                    i = j
                continue

            norm = name.rstrip("*").lower()

            if norm == "verb":  # \verb|code| 原样保留
                if j < n:
                    delim = src[j]
                    k = src.find(delim, j + 1)
                    emit(src[j + 1 : k if k > 0 else n], j + 1, True)
                    i = n if k < 0 else k + 1
                else:
                    i = j
                continue

            ck = cite_kind(norm)
            if ck is not None:
                keys, j2 = _read_cite_args(src, j, norm in _MULTI)
                rep = cite_render(ck + ":" + norm, keys) if cite_render else ""
                start = pos
                emit(rep, i)
                if cite_render and rep:
                    marks.append(RenderedMarker(start, pos, norm, keys))
                i = j2
                continue

            mac = macros.get(name.rstrip("*")) if macros else None
            if mac is not None and _depth < _MAX_DEPTH:
                args, j2 = _read_macro_args(src, j, mac)
                body = _substitute(mac.body, args)[:_MAX_EXPANSION]
                sub, sub_marks, _, _ = render_mapped(
                    body, cite_render, macros, _depth + 1)
                base = pos
                emit(sub, i)
                for sm in sub_marks:
                    marks.append(RenderedMarker(
                        base + sm.start, base + sm.end, sm.name, sm.keys))
                i = j2
                continue

            if norm in _SPACERS:
                emit(_SPACERS[norm], i)
                i = j
                continue
            if norm in _GREEK or norm in _SYMBOLS:
                emit(_GREEK.get(norm) or _SYMBOLS.get(norm) or "", i)
                i = j
                continue
            if norm in _ACCENTS:
                inner, j2 = _accent_arg(src, j)
                emit(unicodedata.normalize("NFC", inner + _ACCENTS[norm]), i)
                i = j2
                continue
            if norm in _DROP_FIRST_ARG:
                r = _read_balanced(src, _skip_ws(src, j), "{", "}")
                i = r[1] if r else j
                continue
            if norm in _DROP_ARG:
                # 可选 [...] 参数 + 一个 {...} 参数一并丢弃
                k = _skip_ws(src, j)
                while k < n and src[k] == "[":
                    r = _read_balanced(src, k, "[", "]")
                    if r is None:
                        break
                    k = _skip_ws(src, r[1])
                r = _read_balanced(src, k, "{", "}")
                i = r[1] if r else j
                continue
            if norm in _DROP_N_ARGS:
                k = j
                if norm in {"newcommand", "renewcommand", "providecommand"}:
                    # \newcommand\foo[1]{..}：名字可不带括号
                    k = _skip_ws(src, k)
                    cm = _CMD_RE.match(src, k)
                    if cm:
                        k = cm.end()
                        need = 1
                    else:
                        need = 2
                else:
                    need = _DROP_N_ARGS[norm]
                for _ in range(need):
                    k = _skip_ws(src, k)
                    while k < n and src[k] == "[":
                        r = _read_balanced(src, k, "[", "]")
                        if r is None:
                            break
                        k = _skip_ws(src, r[1])
                    r = _read_balanced(src, k, "{", "}")
                    if r is None:
                        cm = _CMD_RE.match(src, k) if k < n and src[k] == "\\" else None
                        k = cm.end() if cm else k
                        continue
                    k = r[1]
                am = _ASSIGN_RE.match(src, k) if need == 0 else None
                i = am.end() if am else k
                continue
            if norm == "item":
                k = _skip_ws(src, j)
                if k < n and src[k] == "[":  # \item[label]
                    r = _read_balanced(src, k, "[", "]")
                    if r:
                        lab, _ = render(r[0], None, macros)
                        emit(lab + " ", i)
                        i = r[1]
                        continue
                emit("• ", i)
                i = j
                continue
            if norm == "footnote":  # 脚注内联进段落，与上文隔一个空格
                emit(" ", i)
                i = j
                continue
            # 未知命令：只丢命令本身，参数文本照常流出（\\textbf{x}→x）。
            # 命令后的空格照常输出：\\xspace 之类被丢弃后仍要留出词间距。
            # 紧跟 =数值 的是 TeX 寄存器赋值（\\looseness=-1），一并丢弃
            if j < n and src[j] == "=":
                am = _ASSIGN_RE.match(src, j)
                if am and am.end() > j + 1:
                    j = am.end()
            i = j
            continue

        # ---- 普通字符 -------------------------------------------------
        emit(ch, i, True)
        i += 1

    joined = "".join(out)
    text, back = _collapse(joined)
    stripped = text.strip()
    lead = len(text) - len(text.lstrip())
    fwd = _forward(back, len(joined))
    final_marks = [
        RenderedMarker(
            max(fwd[m.start] - lead, 0),
            max(fwd[m.end] - lead, 0),
            m.name, m.keys,
        )
        for m in marks
    ]
    final_math = []
    for a, b, body in maths:
        fa, fb = max(fwd[a] - lead, 0), min(fwd[b] - lead, len(stripped))
        if fb > fa:
            final_math.append((fa, fb, body))
    runs: list[PosRun] = []
    for k in range(lead, lead + len(stripped)):
        o = back[k]
        s, ex = o_src[o], o_exact[o]
        t = k - lead
        if runs:
            pt, ps, pex = runs[-1]
            if ex and pex and ps + (t - pt) == s:
                continue
            if not ex and not pex and ps == s:
                continue
        runs.append((t, s, ex))
    return stripped, final_marks, runs, final_math


def math_runs(body: str, macros: dict[str, Macro] | None = None
              ) -> list[tuple[str, str]]:
    """行内公式 → [(文本, 样式)]，样式 '' | 'sub' | 'sup'。只做上下标
    这一层结构，其余与 _render_math 的扁平化一致。"""
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            t = _render_math("".join(buf), macros)
            if t:
                out.append((t, ""))
            buf.clear()

    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c in "_^":
            j = _skip_ws(body, i + 1)
            if j < n and body[j] == "{":
                r = _read_balanced(body, j, "{", "}")
                inner, k = (r[0], r[1]) if r else (body[j + 1:], n)
            elif j < n and body[j] == "\\":
                m = _CMD_RE.match(body, j)
                inner, k = (m.group(0), m.end()) if m else (body[j], j + 1)
            elif j < n:
                inner, k = body[j], j + 1
            else:
                inner, k = "", n
            flush()
            t = _render_math(inner, macros).strip()
            if t:
                out.append((t, "sub" if c == "_" else "sup"))
            i = k
            continue
        if c == "\\":
            m = _CMD_RE.match(body, i)
            if m:
                buf.append(m.group(0))
                i = m.end()
                continue
        buf.append(c)
        i += 1
    flush()
    return out


def _collapse(text: str) -> tuple[str, list[int]]:
    """压缩连续空白为一个空格。返回 (新文本, back)；back[k] 是新文本
    位置 k 对应的原文本位置。"""
    out: list[str] = []
    back: list[int] = []
    prev_ws = False
    for i, ch in enumerate(text):
        if ch in " \t\n":
            if not prev_ws:
                out.append(" ")
                back.append(i)
            prev_ws = True
        else:
            out.append(ch)
            back.append(i)
            prev_ws = False
    return "".join(out), back


def _forward(back: list[int], n: int) -> list[int]:
    """back 的逆：原文本位置 i → 新文本中第一个 >= i 的位置。"""
    fwd = [len(back)] * (n + 1)
    k = len(back) - 1
    for i in range(n, -1, -1):
        while k >= 0 and back[k] >= i:
            k -= 1
        fwd[i] = k + 1
    return fwd


def map_position(runs: list[PosRun], t: int) -> tuple[int, bool]:
    """渲染位置 → (源码位置, 是否逐字)。"""
    if not runs:
        return 0, False
    lo, hi = 0, len(runs) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if runs[mid][0] <= t:
            lo = mid
        else:
            hi = mid - 1
    rt, rs, ex = runs[lo]
    return (rs + (t - rt), True) if ex else (rs, False)


def _accent_arg(src: str, i: int) -> tuple[str, int]:
    """变音命令的作用对象：{x}、\\i 这类命令，或下一个字符。"""
    i = _skip_ws(src, i)
    r = _read_balanced(src, i, "{", "}")
    if r is not None:
        inner, _ = render(r[0], None)
        return inner, r[1]
    if i < len(src):
        m = _CMD_RE.match(src, i)
        if m:
            return _SYMBOLS.get(m.group(1), m.group(1)), m.end()
        return src[i], i + 1
    return "", i


# ------------------------------------------------------------ 宏定义收集

_DEF_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)\*?"
    r"\s*\{?\s*\\([a-zA-Z@]+)\s*\}?\s*(?:\[(\d)\])?\s*(\[)?")
_TEXDEF_RE = re.compile(r"\\[gex]?def\s*\\([a-zA-Z@]+)\s*((?:#\d\s*)*)\{")
# 这些名字由块扫描器或 render 的专门分支处理，用户重定义它们不当文本宏
_RESERVED = {
    "section", "subsection", "subsubsection", "chapter", "part",
    "paragraph", "subparagraph", "begin", "end", "item", "cite",
    "input", "include", "bibliography", "bibitem", "caption", "label",
    "ref", "footnote", "title", "author", "maketitle", "newblock",
}


def collect_macros(src: str) -> dict[str, Macro]:
    """收集 \\newcommand / \\def 文本宏（参数个数 ≤ 9）。宏体里出现
    \\begin、\\section 这类结构命令的不收（展开后会破坏块结构）。"""
    macros: dict[str, Macro] = {}
    for m in _DEF_RE.finditer(src):
        name = m.group(1)
        nargs = int(m.group(2) or 0)
        k = m.end()
        default = None
        if m.group(3):  # 可选首参默认值
            r = _read_balanced(src, k - 1, "[", "]")
            if r is None:
                continue
            default, k = r[0], r[1]
        k = _skip_ws(src, k)
        r = _read_balanced(src, k, "{", "}")
        if r is None:
            continue
        _add_macro(macros, name, Macro(nargs, default, r[0]))
    for m in _TEXDEF_RE.finditer(src):
        name = m.group(1)
        nargs = len(re.findall(r"#\d", m.group(2)))
        r = _read_balanced(src, m.end() - 1, "{", "}")
        if r is None:
            continue
        _add_macro(macros, name, Macro(nargs, None, r[0]))
    return macros


def _add_macro(macros: dict[str, Macro], name: str, mac: Macro) -> None:
    if name in _RESERVED or "@" in name:
        return
    if re.search(r"\\(?:begin|end|section|subsection|chapter|par\b|"
                 r"def|newcommand|renewcommand|let|input|include|"
                 r"makeatletter|usepackage|setlength|vspace)", mac.body):
        return
    if cite_kind(name.lower()) is not None:
        return
    macros.setdefault(name, mac)


# ------------------------------------------------------------ 项目展开

_VERB_LINE_RE = re.compile(r"\\verb\*?([^a-zA-Z])")


def comment_spans(text: str) -> list[tuple[int, int]]:
    """% 注释区间（含行尾换行与下一行行首空白，即 TeX 的语义）；
    \\% 转义、\\verb|..| 行内 verbatim 不算注释。"""
    spans: list[tuple[int, int]] = []
    n = len(text)
    line_start = 0
    while line_start <= n:
        line_end = text.find("\n", line_start)
        if line_end < 0:
            line_end = n
        line = text[line_start:line_end]
        if "%" in line:
            verb_spans = []
            for m in _VERB_LINE_RE.finditer(line):
                d = m.group(1)
                end = line.find(d, m.end())
                verb_spans.append((m.start(), len(line) if end < 0 else end + 1))
            i = 0
            while True:
                j = line.find("%", i)
                if j < 0:
                    break
                if any(a <= j < b for a, b in verb_spans):
                    i = j + 1
                    continue
                k, bs = j, 0
                while k > 0 and line[k - 1] == "\\":
                    k -= 1
                    bs += 1
                if bs % 2 == 0:
                    a = line_start + j
                    b = line_end + 1 if line_end < n else n
                    # 整行注释保留换行（不吞掉段落间空行）；行尾注释
                    # 吞掉换行与下一行行首空白
                    if line[:j].strip():
                        while b < n and text[b] in " \t":
                            b += 1
                    else:
                        b = line_end
                    spans.append((a, b))
                    break
                i = j + 1
        line_start = line_end + 1
    return spans


def strip_comments(text: str) -> str:
    """去掉 % 注释（见 comment_spans）。"""
    out, cur = [], 0
    for a, b in comment_spans(text):
        out.append(text[cur:a])
        cur = b
    out.append(text[cur:])
    return "".join(out)


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_tex(path: Path) -> str:
    return strip_comments(read_text(path))


def read_src(path: Path, project: Project) -> Src:
    """读文件 → 去注释后的 Src（映射指向原文件）。"""
    text = read_text(path)
    fidx = project.add(path, text)
    src = Src.of_file(text, fidx)
    return src.edit([(a, b, "") for a, b in comment_spans(text)])


def _resolve_tex(base: Path, name: str, root: Path | None = None) -> Path | None:
    name = name.strip().strip('"')
    bases = [base] if root is None or root == base else [base, root]
    for b in bases:
        for cand in (b / name, b / (name + ".tex")):
            if cand.is_file():
                return cand.resolve()
    return None


_INPUT_RE = re.compile(
    r"\\(input|include|subfile|subfileinclude)\s*\{([^}]*)\}"
)
# TeX 原语写法 \input file（空格/行尾收尾，不带括号）
_INPUT_BARE_RE = re.compile(r"\\(input)\s+([^\s{\\]+)")


def expand_inputs(src: str, base: Path, depth: int = 0,
                  seen: set[Path] | None = None) -> str:
    """纯文本版本（不带映射），供只需要文本的调用方使用。"""
    project = Project(base)
    s = Src.of_file(src, project.add(base / "__inline__.tex", src))
    return expand_inputs_src(s, base, project, base, depth, seen).text


def expand_inputs_src(src: Src, base: Path, project: Project,
                      root: Path | None = None, depth: int = 0,
                      seen: set[Path] | None = None) -> Src:
    """递归展开 \\input/\\include/\\subfile（含 \\input file 无括号
    写法），深度上限 8，防循环。子文件路径先相对当前文件、再相对项目
    根目录解析（LaTeX 以主文件目录为当前目录）。"""
    seen = seen if seen is not None else set()
    if depth > 8:
        return src
    root = root or base
    edits: list[tuple[int, int, str | Src]] = []
    taken: list[tuple[int, int]] = []
    for rx in (_INPUT_RE, _INPUT_BARE_RE):
        for m in rx.finditer(src.text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            f = _resolve_tex(base, m.group(2), root) or \
                _resolve_tex(root, m.group(2), root)
            if f is None or f in seen:
                edits.append((m.start(), m.end(), ""))
                continue
            seen.add(f)
            sub = expand_inputs_src(
                read_src(f, project), f.parent, project, root, depth + 1, seen)
            sep = "\n\n" if m.group(1) == "include" else "\n"
            fi, fp, _ = src.origin(m.start())
            bld = Builder()
            bld.add_text(sep, fi, fp)
            bld.add(sub, 0, len(sub))
            bld.add_text(sep, fi, fp)
            edits.append((m.start(), m.end(), bld.build()))
    return src.edit(edits)


def iter_cite_keys(src: str) -> list[str]:
    """按出现顺序收集所有 \\cite 系列命令里的键（顺序信息，
    用于参考文献首次引用排序）。"""
    keys: list[str] = []
    for m in _CMD_RE.finditer(src):
        name = m.group(1)
        if len(name) == 1 and not name.isalpha():
            continue
        norm = name.rstrip("*").lower()
        if cite_kind(norm) is None:
            continue
        ks, _ = _read_cite_args(src, m.end(), norm in _MULTI)
        keys.extend(ks)
    return keys
