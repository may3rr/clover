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

# ---------------------------------------------------------------- cite 命令

_TEXTUAL = {"citet", "textcite", "citealt"}
_AUTHOR_ONLY = {"citeauthor", "citeauthors"}
_YEAR_ONLY = {"citeyear", "citeyearpar"}
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
_DROP_FIRST_ARG = {"href", "textcolor", "colorlink"}

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


def _render_math(s: str) -> str:
    """数学内容扁平化：\\frac{a}{b}→a/b，希腊字母/符号换 unicode，
    其余命令名丢弃、分组括号去掉。"""
    s = re.sub(
        r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1/\2", s
    )
    s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", s)

    def repl(m: re.Match) -> str:
        name = m.group(1)
        if len(name) == 1 and not name.isalpha():
            return _SYMBOLS.get(name, "") if name != " " else " "
        base = name.rstrip("*")
        return _GREEK.get(base) or _SYMBOLS.get(base) or _SPACERS.get(base, "")

    s = _CMD_RE.sub(repl, s)
    return s.replace("{", "").replace("}", "")


def _collapse(text: str) -> tuple[str, list[int]]:
    """压缩连续空白为一个空格。返回 (新文本, fwd)；fwd[i] 是原文本位置
    i 之前已产出的字符数，用于把旧偏移映射到新文本。"""
    out: list[str] = []
    fwd = [0] * (len(text) + 1)
    prev_ws = False
    for i, ch in enumerate(text):
        fwd[i] = len(out)
        if ch in " \t\n":
            if not prev_ws:
                out.append(" ")
            prev_ws = True
        else:
            out.append(ch)
            prev_ws = False
    fwd[len(text)] = len(out)
    return "".join(out), fwd


def render(
    src: str,
    cite_render: Callable[[str, list[str]], str] | None = None,
) -> tuple[str, list[RenderedMarker]]:
    """渲染 latex 源码为纯文本；返回 (text, markers)。

    cite_render(name, keys) 给出 \\cite 命令的替换文本；为 None 时引用
    命令不产出文本也不记 marker。
    """
    out: list[str] = []
    marks: list[RenderedMarker] = []
    i, n = 0, len(src)
    pos = 0

    def emit(s: str) -> None:
        nonlocal pos
        out.append(s)
        pos += len(s)

    while i < n:
        ch = src[i]

        # ---- 引号与连字符 -------------------------------------------
        for lit, rep in (("``", "“"), ("''", "”"), ("---", "—"),
                         ("--", "–"), ("`", "‘"), ("'", "’")):
            if src.startswith(lit, i):
                emit(rep)
                i += len(lit)
                break
        else:
            lit = None
        if lit is not None:
            continue

        # ---- 数学 ----------------------------------------------------
        if ch == "$":
            if src.startswith("$$", i):
                j = src.find("$$", i + 2)
                j = n - 2 if j < 0 else j
                emit(_render_math(src[i + 2 : j]))
                i = j + 2
            else:
                j = i + 1
                while j < n:
                    if src[j] == "$" and src[j - 1] != "\\":
                        break
                    j += 1
                emit(_render_math(src[i + 1 : min(j, n)]))
                i = j + 1
            continue

        # ---- 分组与特殊字符 ------------------------------------------
        if ch in "{}":
            i += 1
            continue
        if ch == "~":
            emit(" ")
            i += 1
            continue
        if ch == "&":
            emit(" ")
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
                    emit(_render_math(src[j:k]))
                    i = k + (2 if k < n else 0)
                elif name == "\\":
                    emit(" ")
                    i = j
                elif name in _ACCENTS:
                    inner, j2 = _accent_arg(src, j)
                    emit(unicodedata.normalize("NFC", inner + _ACCENTS[name]))
                    i = j2
                elif name in _SPACERS:
                    emit(_SPACERS[name])
                    i = j
                else:
                    emit(_SYMBOLS.get(name, ""))
                    i = j
                continue

            norm = name.rstrip("*").lower()

            if norm == "verb":  # \verb|code| 原样保留
                if j < n:
                    delim = src[j]
                    k = src.find(delim, j + 1)
                    emit(src[j + 1 : k if k > 0 else n])
                    i = n if k < 0 else k + 1
                else:
                    i = j
                continue

            ck = cite_kind(norm)
            if ck is not None:
                keys, j2 = _read_cite_args(src, j, norm in _MULTI)
                rep = cite_render(ck + ":" + norm, keys) if cite_render else ""
                start = pos
                emit(rep)
                if cite_render and rep:
                    marks.append(RenderedMarker(start, pos, norm, keys))
                i = j2
                continue

            if norm in _SPACERS:
                emit(_SPACERS[norm])
                i = j
                continue
            if norm in _GREEK or norm in _SYMBOLS:
                emit(_GREEK.get(norm) or _SYMBOLS.get(norm) or "")
                i = j
                continue
            if norm in _ACCENTS:
                inner, j2 = _accent_arg(src, j)
                emit(unicodedata.normalize("NFC", inner + _ACCENTS[norm]))
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
            if norm == "item":
                emit("• ")
                i = j
                continue
            if norm == "footnote":  # 脚注内联进段落，与上文隔一个空格
                emit(" ")
                i = j
                continue
            # 未知命令：只丢命令本身，参数文本照常流出（\\textbf{x}→x）
            i = j
            continue

        # ---- 普通字符 -------------------------------------------------
        emit(ch)
        i += 1

    text, fwd = _collapse("".join(out))
    stripped = text.strip()
    lead = len(text) - len(text.lstrip())
    final_marks = [
        RenderedMarker(
            max(fwd[m.start] - lead, 0),
            max(fwd[m.end] - lead, 0),
            m.name, m.keys,
        )
        for m in marks
    ]
    return stripped, final_marks


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
            return _SYMBOLS.get(m.group(1), m.group(1)), i + m.end()
        return src[i], i + 1
    return "", i


# ------------------------------------------------------------ 项目展开

_VERB_LINE_RE = re.compile(r"\\verb\*?([^a-zA-Z])")


def strip_comments(text: str) -> str:
    """去掉 % 到行尾的注释；\\% 转义、\\verb|..| 行内 verbatim 保留。"""
    lines = []
    for line in text.split("\n"):
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
                line = line[:j]
                break
            i = j + 1
        lines.append(line)
    return "\n".join(lines)


def read_tex(path: Path) -> str:
    try:
        return strip_comments(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return strip_comments(path.read_text(encoding="latin-1"))


def _resolve_tex(base: Path, name: str) -> Path | None:
    name = name.strip()
    for cand in (base / name, base / (name + ".tex")):
        if cand.is_file():
            return cand.resolve()
    return None


_INPUT_RE = re.compile(
    r"\\(?:input|include|subfile|subfileinclude)\s*\{([^}]*)\}"
)
# TeX 原语写法 \input file（空格/行尾收尾，不带括号）
_INPUT_BARE_RE = re.compile(r"\\input\s+([^\s{]+)")


def expand_inputs(src: str, base: Path, depth: int = 0,
                  seen: set[Path] | None = None) -> str:
    """递归展开 \\input/\\include/\\subfile（含 \\input file 无括号写法），
    深度上限 8，防循环。"""
    seen = seen if seen is not None else set()
    if depth > 8:
        return src

    def repl(m: re.Match) -> str:
        f = _resolve_tex(base, m.group(1))
        if f is None or f in seen:
            return ""
        seen.add(f)
        sub = read_tex(f)
        return "\n\n" + expand_inputs(sub, f.parent, depth + 1, seen) + "\n\n"

    src = _INPUT_RE.sub(repl, src)
    return _INPUT_BARE_RE.sub(repl, src)


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
