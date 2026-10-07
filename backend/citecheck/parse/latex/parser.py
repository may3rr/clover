"""LaTeX 项目 → ParsedDocument。

入口 ``parse_latex(path)``：path 可以是单个 .tex 文件、项目文件夹，
或压缩包（.zip / .tar.gz / arXiv 的 .gz；先安全解压到缓存目录）。

流程：定位主文件 → 读入并去注释 → 展开 \\input/\\include → 摘出
filecontents → 展开正文里的条件 → 改写 cite 别名 → 切出正文 → 扫描
成块（段落 / 各级标题 / thebibliography 区 / \\bibliography 位置标记），
期间剥离浮动体并抢救 \\caption → 收集引用键序 → 解析参考文献
（thebibliography 的 \\bibitem、.bib 文件、或编译产物 .bbl）→ 用引用
样式渲染段落与引用标记。

每一步都在 ``Src`` 上做，渲染文本的任一位置都能追溯回源文件的偏移
（``ParsedDocument.latex``），供报告标注行号与导出批注版源码。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ...refs.structure import parse_authors, parse_reference
from ...schema import (
    CitationMarker,
    Document,
    MathSpan,
    Paragraph,
    Reference,
    Section,
    TableCell,
)
from ..assets import Bundle, bundle_id
from ..headings import canonical_for
from ..parser import LatexMap, ParsedDocument
from . import tex
from .archive import archive_stem, extract_archive, is_archive
from .bib import BibEntry, entry_fields, parse_bib, parse_biblatex_bbl
from .floats import TABULAR_ENVS, scan_float
from .source import Builder, Project, Src

# 整个丢弃的环境（figure/table 会抢救 \\caption 出来当独立段落）
_DROP_ENVS = {
    "figure", "figure*", "table", "table*", "tabular", "tabular*",
    "tabularx", "tabulary", "longtable", "equation", "equation*",
    "align", "align*", "alignat", "alignat*", "gather", "gather*",
    "gathered", "multline", "multline*", "flalign", "flalign*",
    "eqnarray", "eqnarray*", "displaymath", "math", "subequations",
    "verbatim", "verbatim*", "lstlisting", "minted", "Verbatim",
    "tikzpicture", "pgfpicture", "algorithm", "algorithm*", "algorithmic",
    "algorithm2e", "wrapfigure", "wraptable", "subfigure", "picture",
    "comment", "filecontents", "sidewaystable", "sidewaysfigure",
    "tcolorbox", "subtable",
}
_CAPTION_ENVS = {"figure", "figure*", "table", "table*", "wrapfigure",
                 "wraptable", "subfigure", "subtable", "sidewaystable",
                 "sidewaysfigure", "algorithm", "algorithm*"}

_SECTION_LEVELS = {
    "part": 1, "chapter": 1, "section": 1,
    "subsection": 2, "subsubsection": 3,
}
# \paragraph / \subparagraph 是 run-in 标题，按普通文本处理

_MAIN_NAMES = ("main", "paper", "ms", "manuscript", "article", "thesis",
               "root", "index", "report", "acl_latex", "neurips_2024",
               "iclr2025_conference")
_SKIP_DIRS = {"__MACOSX", ".git", "node_modules"}


@dataclass
class Block:
    kind: str  # para | heading | bibliography | autobib
    ranges: list[tuple[int, int]] = field(default_factory=list)
    level: int = 0
    text: str = ""   # 非源码块（如 Abstract 标题）的直接文本
    at: int = 0      # 块起点在正文中的位置（文本块用它定位）
    cell: tuple[str, int, int, int, bool] | None = None  # 表格单元格坐标
    caption: bool = False
    images: list[str] = field(default_factory=list)      # \includegraphics 路径


# ------------------------------------------------------------ 主文件定位

_DOCCLASS_RE = re.compile(r"^[^%\n]*\\documentclass", re.M)


def _tex_files(d: Path) -> list[Path]:
    out = []
    for f in sorted(d.rglob("*.tex")):
        rel = f.relative_to(d)
        if any(p in _SKIP_DIRS or p.startswith(".") for p in rel.parts):
            continue
        if len(rel.parts) > 4:
            continue
        out.append(f)
    return out


def _find_main_tex(d: Path) -> Path:
    """项目主文件：arXiv 00README 指定的 toplevel > 含 \\documentclass
    且不被别的文件 \\input 的文件（常见名、\\begin{document}、浅层优先）。"""
    readme = d / "00README.json"
    if readme.is_file():
        try:
            data = json.loads(readme.read_text(encoding="utf-8"))
            for s in data.get("sources", []):
                if s.get("usage") == "toplevel" and (d / s["filename"]).is_file():
                    return d / s["filename"]
        except (ValueError, KeyError, TypeError, OSError):
            pass
    files = _tex_files(d)
    texts: dict[Path, str] = {}
    for f in files:
        try:
            texts[f] = tex.read_text(f)
        except OSError:
            continue
    cands = [f for f, t in texts.items() if _DOCCLASS_RE.search(t)]
    if not cands:
        if len(files) == 1:
            return files[0]
        raise ValueError(f"{d.name}: 没有找到含 \\documentclass 的 .tex 文件")
    included: set[str] = set()
    for t in texts.values():
        for m in re.finditer(r"\\(?:input|include|subfile)\s*\{([^}]*)\}", t):
            included.add(Path(m.group(1).strip()).stem)

    def score(f: Path) -> tuple:
        t = texts[f]
        rel = f.relative_to(d)
        return (
            "\\begin{document}" in t,
            f.stem not in included,
            f.stem.lower() in _MAIN_NAMES,
            -len(rel.parts),
            len(t),
        )
    return max(cands, key=score)


# ------------------------------------------------------------ 块扫描

_END_THEBIB_RE = re.compile(r"\\end\s*\{thebibliography\}")
_CMD_TOKEN_RE = re.compile(r"\\([a-zA-Z]+\*?)|\n[ \t]*\n")
def _match_env_end(src: str, start: int, env: str) -> int:
    """找与 \\begin{env} 配对的 \\end{env} 的结束位置（嵌套同名计深）。"""
    tok = re.compile(r"\\(begin|end)\s*\{" + re.escape(env) + r"\}")
    depth = 1
    for m in tok.finditer(src, start):
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return m.end()
    return len(src)


def _scan_blocks(body: str) -> tuple[list[Block], dict]:
    """把正文源码切成有序块（块记录的是正文中的区间）。返回
    (blocks, meta)；meta 含 title_src、bib_files、bib_style、nocite。"""
    blocks: list[Block] = []
    meta: dict = {"title_src": None, "bib_files": [], "bib_style": None,
                  "bib_at": None, "tables": 0}
    buf: list[tuple[int, int]] = []

    def flush() -> None:
        if any(body[a:b].strip() for a, b in buf):
            blocks.append(Block("para", list(buf), at=buf[0][0]))
        buf.clear()

    def keep(a: int, b: int) -> None:
        if b > a:
            if buf and buf[-1][1] == a:
                buf[-1] = (buf[-1][0], b)
            else:
                buf.append((a, b))

    i, n = 0, len(body)
    while i < n:
        m = _CMD_TOKEN_RE.search(body, i)
        if not m:
            keep(i, n)
            break
        keep(i, m.start())
        if m.group(1) is None:  # 空行 → 段落边界
            flush()
            i = m.end()
            continue
        name = m.group(1).rstrip("*")
        norm = name.lower()
        j = m.end()

        if norm == "begin":
            r = tex._read_balanced(body, tex._skip_ws(body, j), "{", "}")
            env = r[0].strip() if r else ""
            j = r[1] if r else j
            if env == "thebibliography":
                flush()
                end = _END_THEBIB_RE.search(body, j)
                region_end = end.start() if end else n
                blocks.append(Block("bibliography", [(j, region_end)], at=m.start()))
                i = end.end() if end else n
                continue
            if env == "abstract":
                flush()
                blocks.append(Block("heading", level=1, text="Abstract",
                                    at=m.start()))
                i = j
                continue
            if env in _DROP_ENVS:
                flush()
                end_i = _match_env_end(body, j, env)
                if env in _CAPTION_ENVS or env in TABULAR_ENVS:
                    parts, meta["tables"] = scan_float(
                        body, m.start(), end_i, meta["tables"])
                    for p in parts:
                        blocks.append(Block(
                            "para", p.ranges, at=p.at, cell=p.cell,
                            caption=p.kind == "caption", images=p.images))
                i = end_i
                continue
            # 其它环境：丢掉 begin 标记（含可选参数），内容正常流出
            k = tex._skip_ws(body, j)
            if k < n and body[k] == "[":
                rr = tex._read_balanced(body, k, "[", "]")
                j = rr[1] if rr else j
            i = j
            continue

        if norm == "end":
            r = tex._read_balanced(body, tex._skip_ws(body, j), "{", "}")
            if r and r[0].strip() in {"abstract", "itemize", "enumerate",
                                       "description", "quote", "quotation"}:
                flush()
            i = r[1] if r else j
            continue

        if norm in _SECTION_LEVELS:
            flush()
            k = tex._skip_ws(body, j)
            if k < n and body[k] == "[":  # 可选短标题
                r = tex._read_balanced(body, k, "[", "]")
                k = r[1] if r else k
            k = tex._skip_ws(body, k)
            r = tex._read_balanced(body, k, "{", "}")
            i = r[1] if r else j
            blocks.append(Block(
                "heading", [(k + 1, r[1] - 1)] if r else [],
                _SECTION_LEVELS[norm], at=m.start()))
            continue

        if norm == "par":
            flush()
            i = j
            continue

        if norm in {"title", "author", "date", "affiliation", "address",
                    "thanks", "icmltitle", "icmlauthor", "icmlaffiliation",
                    "icmlcorrespondingauthor", "icmlkeywords"}:
            k = tex._skip_ws(body, j)
            if k < n and body[k] == "[":
                rr = tex._read_balanced(body, k, "[", "]")
                k = tex._skip_ws(body, rr[1]) if rr else k
            r = tex._read_balanced(body, k, "{", "}")
            if norm in {"title", "icmltitle"} and r:
                meta["title_src"] = r[0]
            i = r[1] if r else j
            continue

        if norm in {"maketitle", "appendix", "tableofcontents", "clearpage",
                    "newpage", "onecolumn", "twocolumn"}:
            i = j
            continue

        if norm in {"bibliography", "addbibresource", "printbibliography"}:
            k = tex._skip_ws(body, j)
            r = None
            while k < n and body[k] == "[":
                r = tex._read_balanced(body, k, "[", "]")
                if r is None:
                    break
                k = tex._skip_ws(body, r[1])
            r = tex._read_balanced(body, k, "{", "}") \
                if norm != "printbibliography" else None
            if r:
                for f in r[0].split(","):
                    f = f.strip()
                    if f:
                        meta["bib_files"].append(f)
            if norm in {"bibliography", "printbibliography"}:
                flush()
                blocks.append(Block("autobib", at=m.start()))
                if meta["bib_at"] is None:
                    meta["bib_at"] = m.start()
            i = r[1] if r else k
            continue

        if norm == "bibliographystyle":
            r = tex._read_balanced(body, tex._skip_ws(body, j), "{", "}")
            if r:
                meta["bib_style"] = r[0].strip()
            i = r[1] if r else j
            continue

        if norm == "nocite":
            r = tex._read_balanced(body, tex._skip_ws(body, j), "{", "}")
            if r:
                meta.setdefault("nocite", []).extend(
                    k.strip() for k in r[0].split(",") if k.strip())
            i = r[1] if r else j
            continue

        # 其它命令不切块，留在段落源码里交给 render 处理
        keep(m.start(), j)
        i = j

    flush()
    return blocks, meta


# ------------------------------------------------------------ 预处理

_FILEC_RE = re.compile(
    r"\\begin\s*\{(filecontents\*?\+?)\}\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")


def _extract_filecontents(src: Src) -> tuple[Src, dict[str, tuple[str, int, int]]]:
    """摘出 \\begin{filecontents}{name.bib} ... \\end{filecontents}
    自包含文献（arXiv 单文件提交常见），返回 (去掉该环境的源码,
    虚拟文件名→(内容, 文件序号, 文件内偏移))。"""
    virtual: dict[str, tuple[str, int, int]] = {}
    edits = []
    text = src.text
    for m in _FILEC_RE.finditer(text):
        env, fname = m.group(1), m.group(2).strip()
        end = re.search(r"\\end\s*\{" + re.escape(env) + r"\}", text[m.end():])
        if end is None:
            continue
        f, fp, _ = src.origin(m.end())
        virtual[fname] = (text[m.end(): m.end() + end.start()], f, fp)
        edits.append((m.start(), m.end() + end.end(), ""))
    return src.edit(edits), virtual


_IF_RE = re.compile(r"(?<!\\newif)\\(if[a-zA-Z]*)")
_COND_TOK_RE = re.compile(r"\\(if[a-zA-Z]*|else|or|fi)(?![a-zA-Z])")
_NOT_CONDITIONALS = {"ifthenelse", "ifdefined", "ifcsname", "ifpdf"}


def _eval_conditional(src: str, i: int, name: str) -> tuple[int, int, int]:
    """src[i] 紧跟 \\ifX 之后。返回 (保留区间起点, 终点, \\fi 之后的位置)。

    \\iffalse 只保留 \\else 分支；其余条件无法求值，一律保留真分支、
    丢弃 \\else 分支（乐观策略：模板里常见 \\ifx\\x\\undefined 之类）。"""
    assumed = name != "iffalse"
    depth = 1
    else_span: tuple[int, int] | None = None
    for m in _COND_TOK_RE.finditer(src, i):
        t = m.group(1)
        if t == "fi":
            depth -= 1
            if depth == 0:
                if else_span:
                    return ((i, else_span[0], m.end()) if assumed
                            else (else_span[1], m.start(), m.end()))
                return (i, m.start(), m.end()) if assumed else (i, i, m.end())
        elif t.startswith("if") and t not in _NOT_CONDITIONALS:
            depth += 1
        elif t in {"else", "or"} and depth == 1 and else_span is None:
            else_span = (m.start(), m.end())
    return (i, len(src), len(src)) if assumed else (i, i, len(src))


def _expand_conditionals(src: Src, start: int = 0) -> Src:
    """把 src[start:] 中的 \\if…\\else…\\fi 用假设真分支（\\iffalse 用
    假分支）展开掉。"""
    text = src.text
    edits: list[tuple[int, int, str]] = []
    dropped: list[tuple[int, int]] = []
    pos = start
    while True:
        m = _IF_RE.search(text, pos)
        if not m:
            break
        name = m.group(1).lower()
        hit = next((d for d in dropped if d[0] <= m.start() < d[1]), None)
        if hit:
            pos = hit[1]
            continue
        if name in _NOT_CONDITIONALS:
            pos = m.end()
            continue
        ka, kb, end = _eval_conditional(text, m.end(), name)
        edits.append((m.start(), ka, ""))
        dropped.append((m.start(), ka))
        if kb < end:
            edits.append((kb, end, ""))
            dropped.append((kb, end))
        pos = ka
    return src.edit(edits)


def _rewrite_cite_aliases(src: Src) -> Src:
    """识别 \\let\\mycite\\citep 与 \\newcommand{\\mycite}[1]{\\citep{#1}}
    这类单命令别名，把 \\mycite 改写成 \\citep，让下游统一处理。"""
    text = src.text
    aliases: dict[str, str] = {}
    for m in re.finditer(
        r"\\let\\([a-zA-Z]+)\s*=?\s*\\([a-zA-Z]+\*?)", text
    ):
        if tex.cite_kind(m.group(2).rstrip("*").lower()):
            aliases[m.group(1)] = m.group(2)
    for m in re.finditer(
        r"\\(?:newcommand|renewcommand|providecommand|def)\s*"
        r"\{?\\([a-zA-Z]+)\}?\s*(?:\[\d+\])?\s*(?:#\d\s*)*"
        r"\{((?:[^{}]|\{[^{}]*\})*)\}",
        text,
    ):
        body = m.group(2).strip()
        inner = re.fullmatch(
            r"\\([a-zA-Z]+\*?)\s*(\[[^\]]*\])?\s*(\{[#0-9\s]*\})?\s*", body)
        if inner and tex.cite_kind(inner.group(1).rstrip("*").lower()):
            aliases[m.group(1)] = inner.group(1)
    if not aliases:
        return src
    rx = re.compile(r"\\(" + "|".join(map(re.escape, aliases)) + r")(?![a-zA-Z])")
    edits = [(m.start(), m.end(), "\\" + aliases[m.group(1)])
             for m in rx.finditer(text)]
    return src.edit(edits)


# ------------------------------------------------------------ 引用样式

_AY_BIBSTYLES = re.compile(
    r"nat|apalike|apa|chicago|authordate|agsm|dcu|harvard|abbrvnat|"
    r"plainnat|unsrtnat|humannat|elsarticle-harv|cas-model2|acl|"
    r"iclr|icml|aaai-named|named|colm",
    re.I,
)


def _detect_style(src: str, bib_style: str | None) -> str:
    """numeric | author_year。优先级：biblatex style > natbib 选项 >
    \\bibliographystyle > 默认 numeric（裸 \\cite 输出 [n]）。"""
    for m in re.finditer(
        r"\\usepackage\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}", src
    ):
        opts, pkgs = m.group(1) or "", m.group(2)
        if "biblatex" in pkgs:
            sty = re.search(r"(?:cite|bib)?style\s*=\s*([a-zA-Z0-9_-]+)", opts)
            s = sty.group(1).lower() if sty else "numeric"
            if re.search(r"authoryear|authortitle|apa|mla|chicago|verbose", s):
                return "author_year"
            return "numeric"
        if "natbib" in pkgs and "numbers" in opts:
            return "numeric"
    if bib_style:
        return "author_year" if _AY_BIBSTYLES.search(bib_style) else "numeric"
    if re.search(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{[^}]*natbib", src):
        return "author_year"
    return "numeric"


# ------------------------------------------------------------ 参考文献

_BIBITEM_RE = re.compile(r"\\bibitem\s*(?:\[((?:[^\[\]]|\[[^\]]*\])*)\])?\s*\{")
_BIBITEM_FIELDS_RE = re.compile(
    r"^(?P<a>.+?)\.\s*(?P<y>(?:19|20)\d{2})[a-z]?\.\s*(?P<rest>.+)$", re.S)
_NATBIB_LABEL_RE = re.compile(r"^\{?(?P<short>.*?)\((?P<year>[^()]*)\)(?P<long>.*?)\}?$", re.S)


def _bibitem_fields(raw: str) -> dict:
    """thebibliography 条目的字段抽取。通用 parse_reference 会把
    'Authors. 2020. Title.' 里的年份当标题，所以先试 '作者. 年份. 其余'
    的 BibTeX 输出格式，不匹配再走通用启发式。"""
    m = _BIBITEM_FIELDS_RE.match(raw)
    if not m:
        return parse_reference(raw)
    info = parse_reference(raw)
    info["authors"] = parse_authors(m.group("a"), info["lang"])
    info["year"] = int(m.group("y"))
    chunks = re.split(r"\.\s+", m.group("rest").strip())
    if chunks:
        info["title"] = chunks[0].strip(" .") or info["title"]
        for c in chunks[1:]:
            c = c.strip(" .")
            if c and not re.fullmatch(r"[\d\s:()\-–—,/]+", c):
                info["venue"] = c
                break
    return info


@dataclass
class _RefSrc:
    ref: Reference
    file: int
    fpos: int
    # natbib 的 \bibitem[Short(Year)Long] 标签：作者-年份引用的渲染依据
    short: str | None = None
    year_label: str | None = None
    # 字段来自 .bib / biblatex .bbl 的结构化数据（无需模型再结构化）
    structured: bool = False


def _parse_bibitems(region: Src, style: str,
                    macros: dict[str, tex.Macro]) -> list[_RefSrc]:
    """thebibliography 区 → 条目列表（源码顺序即印刷顺序）。"""
    text = region.text
    items = list(_BIBITEM_RE.finditer(text))
    out: list[_RefSrc] = []
    for idx, m in enumerate(items):
        g = tex._read_balanced(text, m.end() - 1, "{", "}")
        if g is None:
            continue
        key = g[0].strip()
        text_end = items[idx + 1].start() if idx + 1 < len(items) else len(text)
        raw, _ = tex.render(text[g[1]: text_end], None, macros)
        raw = raw.strip()
        if not raw:
            continue
        info = _bibitem_fields(raw)
        opt = m.group(1)
        short = year_label = None
        if opt:
            lm = _NATBIB_LABEL_RE.match(opt.strip())
            if lm and lm.group("year").strip():
                short = tex.render(lm.group("short"))[0].strip() or None
                year_label = tex.render(lm.group("year"))[0].strip() or None
        n = len(out) + 1
        label = None
        if style == "numeric":
            label = opt.strip() if opt and not short else str(n)
        f, fp, _ = region.origin(m.start())
        out.append(_RefSrc(Reference(
            id=f"r{n}", raw=raw,
            title=info["title"], authors=info["authors"], year=info["year"],
            venue=info["venue"], doi=info["doi"], lang=info["lang"],
            label=label, key=key or None,
        ), f, fp, short, year_label))
    return out


def _find_file(projdir: Path, root: Path, name: str, suffix: str) -> Path | None:
    for base in (projdir, root):
        for cand in (base / name, base / (name + suffix)):
            if cand.is_file():
                return cand.resolve()
    return None


def _load_bib_entries(resources: list[str], projdir: Path, root: Path,
                      virtual: dict[str, tuple[str, int, int]],
                      project: Project) -> list[tuple[BibEntry, int, int]]:
    """按 \\bibliography/\\addbibresource 顺序读 .bib → (条目, 文件, 基址)。"""
    seen: set[str] = set()
    out: list[tuple[BibEntry, int, int]] = []
    for name in resources:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        # filecontents 提供的虚拟 .bib 优先于磁盘
        v = virtual.get(name) or virtual.get(name + ".bib") or next(
            (val for k, val in virtual.items() if Path(k).stem == Path(name).stem),
            None)
        if v is not None:
            text, f, base = v
            out += [(e, f, base + e.pos) for e in parse_bib(text)]
            continue
        path = _find_file(projdir, root, name, ".bib")
        if path is None:
            continue
        text = tex.read_text(path)
        fidx = project.add(path, text)
        out += [(e, fidx, e.pos) for e in parse_bib(text)]
    return out


def _find_bbl(main: Path, root: Path) -> Path | None:
    for cand in (main.with_suffix(".bbl"), root / (main.stem + ".bbl")):
        if cand.is_file():
            return cand
    bbls = [p for p in root.rglob("*.bbl")
            if not any(x in _SKIP_DIRS for x in p.relative_to(root).parts)]
    return bbls[0] if len(bbls) == 1 else None


def _bib_refs(entries: list[tuple[BibEntry, int, int]], style: str,
              order_keys: list[str],
              fallback: dict[str, _RefSrc] | None = None) -> list[_RefSrc]:
    """按 order_keys 组装条目；.bib 里没有的键用 fallback（.bbl 条目）。"""
    out: list[_RefSrc] = []
    by_key: dict[str, tuple[BibEntry, int, int]] = {}
    for item in entries:
        by_key.setdefault(item[0].key, item)
    for key in order_keys:
        item = by_key.get(key)
        if item is None:
            x = (fallback or {}).get(key)
            if x is not None:
                n = len(out) + 1
                x.ref.id = f"r{n}"
                if style == "numeric" and not x.ref.label:
                    x.ref.label = str(n)
                out.append(x)
            continue
        e, f, fp = item
        info = entry_fields(e)
        n = len(out) + 1
        out.append(_RefSrc(Reference(
            id=f"r{n}", raw=info["raw"], title=info["title"],
            authors=info["authors"], year=info["year"], venue=info["venue"],
            doi=info["doi"], lang=info["lang"],
            label=str(n) if style == "numeric" else None, key=e.key,
        ), f, fp, structured=True))
    return out


# ------------------------------------------------------------ cite 渲染

def _surname(author: str) -> str:
    a = author.strip()
    if "," in a:
        return a.split(",", 1)[0].strip()
    parts = a.split()
    return parts[-1] if parts else a


def _ay_names(ref: Reference | None) -> str:
    """引用位置的作者渲染：1 人 Surname；2 人 A and B；多人或
    'and others' 收尾 → Surname et al.。"""
    if ref is None or not ref.authors:
        return "?"
    authors = list(ref.authors)
    if authors[-1].strip().lower() in {"others", "other"}:
        authors = authors[:-1] + ["et al."] if len(authors) > 1 else authors
    if authors and authors[-1].strip().lower() == "et al.":
        return f"{_surname(authors[0])} et al."
    if len(authors) == 1:
        return _surname(authors[0])
    if len(authors) == 2:
        return f"{_surname(authors[0])} and {_surname(authors[1])}"
    return f"{_surname(authors[0])} et al."


def _cite_renderer(style: str, keymap: dict[str, Reference],
                   labels: dict[str, tuple[str, str]]):
    """name 形如 'paren:citep' / 'textual:citet' / 'author:citeauthor' /
    'year:citeyear'；keys 是命令里的键列表。返回替换文本。
    labels：natbib .bbl 标签给出的 (作者短名, 年份)，优先于字段推断。"""

    def names(k: str) -> str:
        if k in labels:
            return labels[k][0]
        return _ay_names(keymap.get(k))

    def year(k: str) -> str:
        if k in labels:
            return labels[k][1]
        r = keymap.get(k)
        return str(r.year) if r and r.year else "?"

    def render(name: str, keys: list[str]) -> str:
        if not keys:
            return ""
        kind, _, cmd = name.partition(":")
        if kind == "author":
            return " and ".join(names(k) for k in keys)
        if kind == "year":
            return "; ".join(year(k) for k in keys)
        if style == "author_year":
            # 未定义的键 natbib 只印一个 ?
            known = [k in keymap for k in keys]
            if kind == "textual":
                return "; ".join(f"{names(k)} ({year(k)})" if ok else "?"
                                 for k, ok in zip(keys, known))
            inner = "; ".join(f"{names(k)}, {year(k)}" if ok else "?"
                              for k, ok in zip(keys, known))
            return inner if cmd == "citealp" else f"({inner})"
        # numeric
        if kind == "textual":
            return ", ".join(
                f"{names(k)} [{keymap[k].label}]"
                if k in keymap and keymap[k].label else "?"
                for k in keys)
        return "[" + ",".join(
            keymap[k].label if k in keymap and keymap[k].label else "?"
            for k in keys) + "]"

    return render


# ------------------------------------------------------------ 位置映射

def _compose(runs: list[tex.PosRun], length: int, block: Src
             ) -> list[tuple[int, int, int, bool]]:
    """渲染映射 ∘ 块映射 → 段落位置到 (文件, 文件偏移) 的分段表。"""
    out: list[tuple[int, int, int, bool]] = []

    def push(t: int, f: int, fp: int, ex: bool) -> None:
        if out:
            pt, pf, pfp, pex = out[-1]
            if pt == t:
                out[-1] = (t, f, fp, ex)
                return
            if ex and pex and pf == f and pfp + (t - pt) == fp:
                return
            if not ex and not pex and pf == f and pfp == fp:
                return
        out.append((t, f, fp, ex))

    for k, (t, s, ex) in enumerate(runs):
        t_end = runs[k + 1][0] if k + 1 < len(runs) else length
        if not ex:
            f, fp, _ = block.origin(s)
            push(t, f, fp, False)
            continue
        # 逐字段：按块映射的分段边界再切
        s_end = s + (t_end - t)
        pos = s
        while pos < s_end:
            f, fp, bex = block.origin(pos)
            kseg = max(_bisect(block._keys, pos), 0)
            nxt = block._keys[kseg + 1] if kseg + 1 < len(block._keys) else s_end
            stop = min(max(nxt, pos + 1), s_end)
            push(t + (pos - s), f, fp, bex)
            pos = stop
    return out


def _bisect(keys: list[int], pos: int) -> int:
    lo, hi = 0, len(keys)
    while lo < hi:
        mid = (lo + hi) // 2
        if keys[mid] <= pos:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


# ------------------------------------------------------------ 主入口

_DOC_BEGIN = re.compile(r"\\begin\s*\{document\}")
_DOC_END = re.compile(r"\\end\s*\{document\}")


def parse_latex(path: str | Path) -> ParsedDocument:
    path = Path(path)
    filename = path.name
    if is_archive(path):
        root = extract_archive(path)
        main = _find_main_tex(root)
    elif path.is_dir():
        root = path
        main = _find_main_tex(path)
    else:
        root = path.parent
        main = path
    project = Project(root)
    src = tex.expand_inputs_src(
        tex.read_src(main, project), main.parent, project, main.parent)
    src, virtual_files = _extract_filecontents(src)
    bm = _DOC_BEGIN.search(src.text)
    src = _expand_conditionals(src, bm.end() if bm else 0)
    src = _rewrite_cite_aliases(src)
    macros = tex.collect_macros(src.text)

    # body：\begin{document} 与 \end{document} 之间；没有 document 环境
    # 就把整个文件当正文（片段式 .tex）。
    bm, em = _DOC_BEGIN.search(src.text), _DOC_END.search(src.text)
    b0 = bm.end() if bm else 0
    b1 = em.start() if (bm and em and em.start() > b0) else len(src.text)
    body = src.slice(b0, b1)

    blocks, meta = _scan_blocks(body.text)
    # biblatex 的 \addbibresource 标准位置在导言区
    preamble = src.text[: bm.start()] if bm else ""
    pre_bibs = [
        f.strip()
        for m in re.finditer(
            r"\\addbibresource\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", preamble)
        for f in m.group(1).split(",")
        if f.strip()
    ]
    meta["bib_files"] = pre_bibs + meta["bib_files"]
    style = _detect_style(src.text, meta["bib_style"])

    # 参考文献：正文 thebibliography > .bib（.bbl 给出印刷顺序）> .bbl
    bib_block = next((b for b in blocks if b.kind == "bibliography"), None)
    cite_order = list(dict.fromkeys(tex.iter_cite_keys(body.text)))
    nocite = meta.get("nocite", [])
    ref_srcs: list[_RefSrc] = []
    if bib_block is not None:
        a, b = bib_block.ranges[0]
        ref_srcs = _parse_bibitems(body.slice(a, b), style, macros)
    else:
        bbl_path = _find_bbl(main, root)
        bbl_text = tex.read_text(bbl_path) if bbl_path else None
        bbl_idx = project.add(bbl_path, bbl_text) if bbl_path else -1
        entries = _load_bib_entries(
            meta["bib_files"], main.parent, root, virtual_files, project)
        bbl_items: list[_RefSrc] = []
        bbl_entries: list[BibEntry] = []
        if bbl_text:
            tb = re.search(r"\\begin\s*\{thebibliography\}", bbl_text)
            if tb:
                bbl_items = _parse_bibitems(
                    Src.of_file(bbl_text, bbl_idx).slice(
                        tb.end(), len(bbl_text)), style, macros)
            else:
                bbl_entries = parse_biblatex_bbl(bbl_text)
        if entries:
            if bbl_items or bbl_entries:
                # 编译产物给出真实印刷顺序与完整条目集；字段优先取 .bib
                # （.bib 缺失的条目——作者引用了未随稿提交的库——退回
                # .bbl 自身的内容）
                order = [x.ref.key for x in bbl_items] or \
                    [e.key for e in bbl_entries]
                order += [k for k in cite_order if k not in set(order)]
            elif "*" in nocite:
                order = list(dict.fromkeys(
                    cite_order + [e.key for e, _, _ in entries]))
            elif style == "numeric":
                order = list(dict.fromkeys(cite_order + nocite))
            else:
                wanted = set(cite_order) | set(nocite)
                order = [e.key for e, _, _ in entries if e.key in wanted]
            fallback = {x.ref.key: x for x in bbl_items}
            fallback_entries = [(e, bbl_idx, e.pos) for e in bbl_entries]
            ref_srcs = _bib_refs(entries + fallback_entries, style, order,
                                 fallback)
            # natbib 标签（作者短名与年份）仍取自 .bbl
            for r in ref_srcs:
                x = fallback.get(r.ref.key)
                if x is not None and x is not r:
                    r.short, r.year_label = x.short, x.year_label
                    if style == "numeric" and x.ref.label:
                        r.ref.label = x.ref.label
        elif bbl_items:
            ref_srcs = bbl_items
        elif bbl_entries:
            ref_srcs = _bib_refs(
                [(e, bbl_idx, e.pos) for e in bbl_entries], style,
                [e.key for e in bbl_entries])

    references = [x.ref for x in ref_srcs]
    keymap = {r.key: r for r in references if r.key}
    labels = {x.ref.key: (x.short, x.year_label) for x in ref_srcs
              if x.ref.key and x.short and x.year_label}
    render_cite = _cite_renderer(style, keymap, labels)

    # ---- 组装段落 / 节 / 标记 -------------------------------------------
    texts: list[str] = []
    para_section: list[str] = []
    p_ids: list[str] = []
    heading_levels: list[int | None] = []
    markers: list[CitationMarker] = []
    para_runs: dict[str, list[tuple[int, int, int, bool]]] = {}
    para_math: dict[str, list[MathSpan]] = {}
    para_cell: dict[str, TableCell] = {}
    para_images: dict[str, list[str]] = {}
    para_caption: set[str] = set()
    figures = _Figures(src.text, main.parent, root)

    sections: list[Section] = []
    cur: Section | None = None

    def new_section(title: str, canonical: str, hp: str | None) -> Section:
        s = Section(id=f"s{len(sections)}", title=title, canonical=canonical,
                    heading_paragraph_id=hp)
        sections.append(s)
        return s

    def add_para(text: str, heading: int | None = None) -> str:
        pid = f"p{len(p_ids)}"
        nonlocal cur
        if heading == 1:
            cur = new_section(text, canonical_for(text), pid)
        if cur is None:
            cur = new_section("", "other", None)
        p_ids.append(pid)
        texts.append(text)
        para_section.append(cur.id)
        heading_levels.append(heading)
        return pid

    bib_emitted = False

    def emit_bibliography(at: int) -> None:
        nonlocal bib_emitted
        if bib_emitted or not references:
            bib_emitted = True
            return
        bib_emitted = True
        hp = add_para("References", heading=1)
        f, fp, _ = body.origin(at)
        para_runs[hp] = [(0, f, fp, False)]
        for x in ref_srcs:
            pid = add_para(x.ref.raw)
            x.ref.paragraph_id = pid
            para_runs[pid] = [(0, x.file, x.fpos, False)]

    for b in blocks:
        if b.kind in {"bibliography", "autobib"}:
            emit_bibliography(b.at)
            continue
        if b.text:
            pid = add_para(b.text, heading=b.level or None)
            f, fp, _ = body.origin(b.at)
            para_runs[pid] = [(0, f, fp, False)]
            continue
        bld = Builder()
        for a, e in b.ranges:
            bld.add(body, a, e)
        block_src = bld.build()
        t, ms, runs, maths = tex.render_mapped(
            block_src.text, render_cite, macros)
        imgs = [n for n in (figures.add(x) for x in b.images) if n]
        if not t and not imgs:
            continue
        pid = add_para(t, heading=b.level if b.kind == "heading" else None)
        if b.cell:
            tid, row, col, span, head = b.cell
            para_cell[pid] = TableCell(table=tid, row=row, col=col,
                                       colspan=span, header=head)
        if imgs:
            para_images[pid] = imgs
        if b.caption:
            para_caption.add(pid)
        if not t:
            f, fp, _ = body.origin(b.at)
            para_runs[pid] = [(0, f, fp, False)]
            continue
        para_runs[pid] = _compose(runs, len(t), block_src)
        if maths:
            para_math[pid] = [
                MathSpan(start=a, end=e, runs=tex.math_runs(body, macros))
                for a, e, body in maths]
        for m in ms:
            markers.append(CitationMarker(
                id=f"m{len(markers)}", paragraph_id=pid,
                start=m.start, end=m.end,
                raw=t[m.start:m.end], kind="cite_key", keys=m.keys,
                ref_ids=[keymap[k].id for k in m.keys if k in keymap]))

    emit_bibliography(meta["bib_at"] or len(body.text))

    # ---- 文档元信息 -------------------------------------------------------
    title_src = meta["title_src"]
    if title_src is None:  # \title 通常在导言区
        tm = re.search(r"\\(?:icml)?title(?![a-zA-Z])\s*(?:\[[^\]]*\])?\s*", src.text)
        if tm:
            r = tex._read_balanced(src.text, tex._skip_ws(src.text, tm.end()), "{", "}")
            title_src = r[0] if r else None
    title = tex.render(title_src, None, macros)[0] if title_src else None
    if not title:
        title = next(
            (t.strip() for t, lv in zip(texts, heading_levels)
             if lv == 1 and t.strip() and t != "Abstract"), None)
    if not title:
        title = archive_stem(Path(filename)) if is_archive(path) \
            else Path(filename).stem

    char_offsets: list[int] = []
    cursor = 0
    for t in texts:
        char_offsets.append(cursor)
        cursor += len(t) + 1

    word_count = sum(
        len(re.findall(r"[\w一-鿿]+", t)) for t in texts)

    paragraphs = [
        Paragraph(id=p_ids[i], section_id=para_section[i], text=texts[i],
                  char_offset=char_offsets[i],
                  math=para_math.get(p_ids[i], []),
                  cell=para_cell.get(p_ids[i]),
                  images=para_images.get(p_ids[i], []),
                  caption=p_ids[i] in para_caption)
        for i in range(len(texts))
    ]

    return ParsedDocument(
        document=Document(
            title=title, filename=filename, source_format="tex",
            citation_style=style,  # type: ignore[arg-type]
            word_count=word_count,
            assets=figures.bundle.id if figures.bundle.used else None,
        ),
        sections=sections,
        paragraphs=paragraphs,
        markers=markers,
        references=references,
        latex=LatexMap(
            root=str(root), main=main.resolve().relative_to(
                root.resolve()).as_posix() if _under(main, root) else main.name,
            files=[f.rel for f in project.files],
            para_runs=para_runs,
        ),
        structured_refs=[x.ref.id for x in ref_srcs if x.structured],
        cited_keys=([r.key for r in references if r.key] if "*" in nocite
                    else list(dict.fromkeys(cite_order + nocite))),
    )


_GRAPHICSPATH_RE = re.compile(r"\\graphicspath\s*\{((?:\s*\{[^{}]*\})+)\s*\}")
_GRAPHIC_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".gif")


class _Figures:
    """\\includegraphics 路径 → 资源包里的图片名（按 \\graphicspath 与
    LaTeX 的扩展名顺序查找；项目外与找不到的路径跳过）。"""

    def __init__(self, text: str, base: Path, root: Path):
        self.base, self.root = base, root
        self.dirs = [""]
        for m in _GRAPHICSPATH_RE.finditer(text):
            self.dirs += re.findall(r"\{([^{}]*)\}", m.group(1))
        self.bundle = Bundle(bundle_id("x", str(root.resolve())))
        self._seen: dict[str, str | None] = {}

    def _resolve(self, name: str) -> Path | None:
        name = name.strip().strip('"')
        for d in self.dirs:
            p = self.base / d / name
            cands = [p] if p.suffix.lower() in _GRAPHIC_EXTS else []
            cands += [p.with_name(p.name + e) for e in _GRAPHIC_EXTS]
            for c in cands:
                if c.is_file() and _under(c, self.root):
                    return c
        return None

    def add(self, name: str) -> str | None:
        if name not in self._seen:
            p = self._resolve(name)
            stem = p.resolve().relative_to(self.root.resolve()).with_suffix(
                "").as_posix() if p else ""
            self._seen[name] = self.bundle.add_file(p, stem) if p else None
        return self._seen[name]


def _under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
