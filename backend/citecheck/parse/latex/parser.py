"""LaTeX 项目 → ParsedDocument。

入口 ``parse_latex(path)``：path 可以是单个 .tex 文件，也可以是项目
文件夹（自动找含 \\documentclass 的主文件）。

流程：读入主文件 → 展开 \\input/\\include → 去掉 \\begin{document} 之
外的部分 → 扫描成块（段落 / 各级标题 / thebibliography 区 /
\\bibliography 位置标记），期间剥离浮动体等环境 → 收集引用键序 →
解析参考文献（thebibliography 的 \\bibitem，或 \\bibliography /
\\addbibresource 指向的 .bib 文件）→ 用引用样式渲染段落与引用标记。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ...refs.structure import parse_authors, parse_reference
from ...schema import (
    CitationMarker,
    Document,
    Paragraph,
    Reference,
    Section,
)
from ..headings import canonical_for
from ..parser import ParsedDocument
from . import tex
from .bib import BibEntry, entry_fields, parse_bib

# 整个丢弃的环境（figure/table 会抢救 \\caption 出来当独立段落）
_DROP_ENVS = {
    "figure", "figure*", "table", "table*", "tabular", "tabular*",
    "tabularx", "tabulary", "longtable", "equation", "equation*",
    "align", "align*", "alignat", "alignat*", "gather", "gather*",
    "gathered", "multline", "multline*", "flalign", "flalign*",
    "eqnarray", "eqnarray*", "displaymath", "math", "subequations",
    "verbatim", "verbatim*", "lstlisting", "minted", "Verbatim",
    "tikzpicture", "pgfpicture", "algorithm", "algorithmic",
    "algorithm2e", "wrapfigure", "wraptable", "subfigure", "picture",
    "comment", "filecontents", "sidewaystable", "sidewaysfigure",
}
_CAPTION_ENVS = {"figure", "figure*", "table", "table*", "wrapfigure",
                 "wraptable", "subfigure", "sidewaystable", "sidewaysfigure"}

_SECTION_LEVELS = {
    "part": 1, "chapter": 1, "section": 1,
    "subsection": 2, "subsubsection": 3,
}
# \paragraph / \subparagraph 是 run-in 标题，按普通文本处理

_MAIN_NAMES = ("main", "paper", "ms", "manuscript", "article", "thesis",
               "root", "index", "report")


@dataclass
class Block:
    kind: str  # para | heading | bibliography | autobib
    src: str = ""
    level: int = 0


# ------------------------------------------------------------ 主文件定位

def _find_main_tex(d: Path) -> Path:
    """目录里含 \\documentclass 的 .tex；常见名优先。"""
    cands: list[Path] = []
    for depth in ("*.tex", "*/*.tex"):
        for f in sorted(d.glob(depth)):
            try:
                if "\\documentclass" in f.read_text(
                    encoding="utf-8", errors="ignore"
                )[:4000]:
                    cands.append(f)
            except OSError:
                continue
        if cands:
            break
    if not cands:
        raise ValueError(f"{d.name}: 没有找到含 \\documentclass 的 .tex 文件")
    for name in _MAIN_NAMES:
        for f in cands:
            if f.stem.lower() == name:
                return f
    return cands[0]


# ------------------------------------------------------------ 块扫描

_BEGIN_RE = re.compile(r"\\begin\s*\{([^}]*)\}")
_END_THEBIB_RE = re.compile(r"\\end\s*\{thebibliography\}")
_CMD_TOKEN_RE = re.compile(r"\\([a-zA-Z]+\*?)|\n[ \t]*\n")
_CAPTION_RE = re.compile(r"\\caption\s*(?:\[[^\]]*\])?\s*\{")


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
    """把正文源码切成有序块。返回 (blocks, meta)；meta 含 title_src、
    bib_files、bib_style、found_bibliography_cmd。"""
    blocks: list[Block] = []
    meta: dict = {"title_src": None, "bib_files": [], "bib_style": None}
    buf: list[str] = []

    def flush() -> None:
        t = "".join(buf)
        buf.clear()
        if t.strip():
            blocks.append(Block("para", t))

    i, n = 0, len(body)
    while i < n:
        m = _CMD_TOKEN_RE.search(body, i)
        if not m:
            buf.append(body[i:])
            break
        buf.append(body[i : m.start()])
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
                blocks.append(Block("bibliography", body[j:region_end]))
                i = end.end() if end else n
                continue
            if env in _DROP_ENVS:
                flush()
                end_i = _match_env_end(body, j, env)
                if env in _CAPTION_ENVS:
                    for cm in _CAPTION_RE.finditer(body, j, end_i):
                        g = tex._read_balanced(
                            body, cm.end() - 1, "{", "}")
                        if g:
                            blocks.append(Block("para", g[0]))
                i = end_i
                continue
            # 其它环境：丢掉 begin 标记，内容正常流出
            i = j
            continue

        if norm == "end":
            r = tex._read_balanced(body, tex._skip_ws(body, j), "{", "}")
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
            title_src = r[0] if r else ""
            i = r[1] if r else j
            blocks.append(Block("heading", title_src, _SECTION_LEVELS[norm]))
            continue

        if norm == "par":
            flush()
            i = j
            continue

        if norm == "title" or norm == "author" or norm == "date":
            r = tex._read_balanced(body, tex._skip_ws(body, j), "{", "}")
            if norm == "title" and r:
                meta["title_src"] = r[0]
            i = r[1] if r else j
            continue

        if norm == "maketitle":
            i = j
            continue

        if norm in {"bibliography", "addbibresource", "printbibliography"}:
            k = tex._skip_ws(body, j)
            while k < n and body[k] == "[":
                r = tex._read_balanced(body, k, "[", "]")
                k = tex._skip_ws(body, r[1] if r else k)
                if r is None:
                    break
            r = tex._read_balanced(body, k, "{", "}")
            if norm != "printbibliography" and r:
                for f in r[0].split(","):
                    f = f.strip()
                    if f:
                        meta["bib_files"].append(f)
            if norm in {"bibliography", "printbibliography"}:
                flush()
                blocks.append(Block("autobib"))
            i = r[1] if r else j
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
        buf.append(body[m.start() : j])
        i = j

    flush()
    return blocks, meta


# ------------------------------------------------------------ 预处理

_FILEC_RE = re.compile(
    r"\\begin\s*\{(filecontents\*?\+?)\}\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")


def _extract_filecontents(src: str) -> tuple[str, dict[str, str]]:
    """摘出 \\begin{filecontents}{name.bib} ... \\end{filecontents}
    自包含文献（arXiv 单文件提交常见），返回 (去掉该环境的源码,
    虚拟文件名→内容)。"""
    virtual: dict[str, str] = {}
    spans: list[tuple[int, int]] = []
    for m in _FILEC_RE.finditer(src):
        env, fname = m.group(1), m.group(2).strip()
        end = re.search(r"\\end\s*\{" + re.escape(env) + r"\}", src[m.end():])
        if end is None:
            continue
        virtual[fname] = src[m.end() : m.end() + end.start()]
        spans.append((m.start(), m.end() + end.end()))
    for a, b in reversed(spans):
        src = src[:a] + src[b:]
    return src, virtual


_IF_RE = re.compile(r"\\(if[a-zA-Z]*)")
_COND_TOK_RE = re.compile(r"\\(if[a-zA-Z]*|else|or|fi)\b")


def _eval_conditional(src: str, i: int, name: str) -> tuple[str, int]:
    """src[i] 紧跟 \\ifX 之后。返回 (保留源码, \\fi 后位置)。

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
                    kept = src[i : else_span[0]] if assumed \
                        else src[else_span[1] : m.start()]
                else:
                    kept = src[i : m.start()] if assumed else ""
                return kept, m.end()
        elif t.startswith("if"):
            depth += 1
        elif t in {"else", "or"} and depth == 1 and else_span is None:
            else_span = (m.start(), m.end())
    return (src[i:] if assumed else ""), len(src)


def _expand_conditionals(src: str) -> str:
    """把 \\if…\\else…\\fi 用假设真分支（\\iffalse 用假分支）展开掉。"""
    while True:
        m = _IF_RE.search(src)
        if not m:
            return src
        keep, end = _eval_conditional(src, m.end(), m.group(1).lower())
        src = src[: m.start()] + keep + src[end:]


def _rewrite_cite_aliases(src: str) -> str:
    """识别 \\let\\mycite\\citep 与 \\newcommand{\\mycite}[1]{\\citep{#1}}
    这类单命令别名，把 \\mycite 改写成 \\citep，让下游统一处理。"""
    aliases: dict[str, str] = {}
    for m in re.finditer(
        r"\\let\\([a-zA-Z]+)\s*=?\s*\\([a-zA-Z]+\*?)", src
    ):
        if tex.cite_kind(m.group(2).rstrip("*").lower()):
            aliases[m.group(1)] = m.group(2)
    for m in re.finditer(
        r"\\(?:newcommand|renewcommand|providecommand|def)\s*"
        r"\{?\\([a-zA-Z]+)\}?\s*(?:\[\d+\])?\s*(?:#\d\s*)*"
        r"\{((?:[^{}]|\{[^{}]*\})*)\}",
        src,
    ):
        body = m.group(2).strip()
        inner = re.fullmatch(
            r"\\([a-zA-Z]+\*?)\s*(\[[^\]]*\])?\s*(\{[#0-9\s]*\})?\s*", body)
        if inner and tex.cite_kind(inner.group(1).rstrip("*").lower()):
            aliases[m.group(1)] = inner.group(1)
    for name, target in aliases.items():
        src = re.sub(r"\\" + re.escape(name) + r"(?![a-zA-Z])",
                     lambda _m, t=target: "\\" + t, src)
    return src


# ------------------------------------------------------------ 引用样式

_AY_BIBSTYLES = re.compile(
    r"nat|apalike|apa|chicago|authordate|agsm|dcu|harvard|abbrvnat|"
    r"plainnat|unsrtnat|humannat|elsarticle-harv|cas-model2",
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
        if "natbib" in pkgs:
            return "numeric" if "numbers" in opts else "author_year"
    if bib_style:
        return "author_year" if _AY_BIBSTYLES.search(bib_style) else "numeric"
    return "numeric"


# ------------------------------------------------------------ 参考文献

_BIBITEM_RE = re.compile(r"\\bibitem\s*(?:\[([^\]]*)\])?\s*\{")
_BIBITEM_FIELDS_RE = re.compile(
    r"^(?P<a>.+?)\.\s*(?P<y>(?:19|20)\d{2})[a-z]?\.\s*(?P<rest>.+)$", re.S)


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


def _parse_bibitems(region: str, style: str) -> list[Reference]:
    """thebibliography 区 → Reference 列表（源码顺序即印刷顺序）。"""
    items = list(_BIBITEM_RE.finditer(region))
    refs: list[Reference] = []
    for idx, m in enumerate(items):
        g = tex._read_balanced(region, m.end() - 1, "{", "}")
        if g is None:
            continue
        key = g[0].strip()
        text_end = items[idx + 1].start() if idx + 1 < len(items) else len(region)
        raw, _ = tex.render(region[g[1] : text_end])
        raw = raw.strip()
        if not raw:
            continue
        info = _bibitem_fields(raw)
        refs.append(Reference(
            id=f"r{len(refs) + 1}",
            raw=raw,
            title=info["title"], authors=info["authors"], year=info["year"],
            venue=info["venue"], doi=info["doi"], lang=info["lang"],
            label=(m.group(1) or str(len(refs) + 1))
                  if style == "numeric" else None,
            key=key or None,
        ))
    return refs


def _load_bib_refs(resources: list[str], projdir: Path, style: str,
                   cite_order: list[str], nocite: list[str],
                   virtual: dict[str, str]) -> list[Reference]:
    """按 \\bibliography/\\addbibresource 顺序读 .bib，合成 Reference。

    .bib 是数据库：只有被 \\cite / \\nocite 点名的条目才会出现在排版
    后的参考文献里，因此未引用条目不进列表（norms 的"未被引用"检查
    对它们不适用）。"""
    seen_files: set[str] = set()
    entries: list[BibEntry] = []
    for name in resources:
        name = name.strip()
        if name in seen_files:
            continue
        # filecontents 提供的虚拟 .bib 优先于磁盘
        vtext = virtual.get(name) or virtual.get(name + ".bib") or next(
            (v for k, v in virtual.items() if Path(k).stem == Path(name).stem),
            None)
        seen_files.add(name)
        if vtext is not None:
            entries += parse_bib(vtext)
            continue
        f = None
        for cand in (projdir / name, projdir / (name + ".bib")):
            if cand.is_file():
                f = cand.resolve()
                break
        if f is None:
            continue
        try:
            entries += parse_bib(f.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            entries += parse_bib(f.read_text(encoding="latin-1"))

    key_set = {e.key for e in entries}
    if "*" in nocite:
        keep = set(key_set)
    else:
        keep = set(cite_order) | set(nocite)
    order = [i for i, e in enumerate(entries) if e.key in keep]
    if style == "numeric" and cite_order:
        pos = {e.key: i for i, e in enumerate(entries)}
        front = [pos[k] for k in dict.fromkeys(cite_order) if k in pos]
        order = front + [i for i in order if i not in set(front)]

    refs: list[Reference] = []
    for i in order:
        e = entries[i]
        info = entry_fields(e)
        refs.append(Reference(
            id=f"r{len(refs) + 1}", raw=info["raw"], title=info["title"],
            authors=info["authors"], year=info["year"], venue=info["venue"],
            doi=info["doi"], lang=info["lang"],
            label=str(len(refs) + 1) if style == "numeric" else None,
            key=e.key,
        ))
    return refs


# ------------------------------------------------------------ cite 渲染

def _surname(author: str) -> str:
    a = author.strip()
    if "," in a:
        return a.split(",", 1)[0].strip()
    parts = a.split()
    return parts[-1] if parts else a


def _ay_names(ref: Reference | None) -> str:
    """引用位置的作者渲染：1 人 Surname；2 人 A & B；多人或
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
        return f"{_surname(authors[0])} & {_surname(authors[1])}"
    return f"{_surname(authors[0])} et al."


def _cite_renderer(style: str, keymap: dict[str, Reference]):
    """name 形如 'paren:citep' / 'textual:citet' / 'author:citeauthor' /
    'year:citeyear'；keys 是命令里的键列表。返回替换文本。"""

    def render(name: str, keys: list[str]) -> str:
        if not keys:
            return ""
        kind, _, _cmd = name.partition(":")
        refs = [keymap.get(k) for k in keys]
        if kind == "author":
            return " & ".join(_ay_names(r) for r in refs)
        if kind == "year":
            return "; ".join(str(r.year) if r and r.year else "?"
                             for r in refs)
        if style == "author_year":
            if kind == "textual":
                return "; ".join(
                    f"{_ay_names(r)} ({r.year})" if r and r.year else
                    f"{_ay_names(r)} (?)" if r else "?"
                    for r in refs)
            return "(" + "; ".join(
                f"{_ay_names(r)}, {r.year}" if r and r.year else
                f"{_ay_names(r)}" if r else "?"
                for r in refs) + ")"
        # numeric
        if kind == "textual":
            return ", ".join(
                f"{_ay_names(r)} [{r.label}]" if r and r.label else "?"
                for r in refs)
        return "[" + ",".join(r.label if r and r.label else "?"
                              for r in refs) + "]"

    return render


# ------------------------------------------------------------ 主入口

_DOC_BEGIN = re.compile(r"\\begin\s*\{document\}")
_DOC_END = re.compile(r"\\end\s*\{document\}")


def parse_latex(path: str | Path) -> ParsedDocument:
    path = Path(path)
    if path.is_dir():
        main = _find_main_tex(path)
        filename = path.name
    else:
        main = path
        filename = path.name
    src = tex.expand_inputs(tex.read_tex(main), main.parent)
    src, virtual_files = _extract_filecontents(src)
    src = _expand_conditionals(src)
    src = _rewrite_cite_aliases(src)

    # body：\begin{document} 与 \end{document} 之间；没有 document 环境
    # 就把整个文件当正文（片段式 .tex）。
    bm, em = _DOC_BEGIN.search(src), _DOC_END.search(src)
    body = src[bm.end():em.start()] if bm else src

    blocks, meta = _scan_blocks(body)
    # biblatex 的 \addbibresource 标准位置在导言区
    preamble = src[: bm.start()] if bm else ""
    pre_bibs = [
        f.strip()
        for m in re.finditer(
            r"\\addbibresource\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", preamble)
        for f in m.group(1).split(",")
        if f.strip()
    ]
    meta["bib_files"] = pre_bibs + meta["bib_files"]
    style = _detect_style(src, meta["bib_style"])

    # 参考文献：thebibliography 优先，其次 .bib 文件
    bib_region = next((b.src for b in blocks if b.kind == "bibliography"), None)
    full_cite_order = tex.iter_cite_keys(body)
    references: list[Reference] = []
    if bib_region is not None:
        references = _parse_bibitems(bib_region, style)
    elif meta["bib_files"]:
        references = _load_bib_refs(
            meta["bib_files"], main.parent, style, full_cite_order,
            meta.get("nocite", []), virtual_files)
    keymap = {r.key: r for r in references if r.key}
    render_cite = _cite_renderer(style, keymap)

    # ---- 组装段落 / 节 / 标记 -------------------------------------------
    texts: list[str] = []
    para_section: list[str] = []
    p_ids: list[str] = []
    heading_levels: list[int | None] = []
    markers: list[CitationMarker] = []

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

    def emit_bibliography() -> None:
        nonlocal bib_emitted
        if bib_emitted or not references:
            bib_emitted = True
            return
        bib_emitted = True
        add_para("References", heading=1)
        for r in references:
            pid = add_para(r.raw)
            r.paragraph_id = pid

    for b in blocks:
        if b.kind in {"bibliography", "autobib"}:
            emit_bibliography()
            continue
        t, ms = tex.render(b.src, render_cite)
        if not t:
            continue
        pid = add_para(t, heading=b.level if b.kind == "heading" else None)
        for m in ms:
            markers.append(CitationMarker(
                id=f"m{len(markers)}", paragraph_id=pid,
                start=m.start, end=m.end,
                raw=t[m.start:m.end], kind="cite_key", keys=m.keys,
                ref_ids=[keymap[k].id for k in m.keys if k in keymap]))

    emit_bibliography()

    # ---- 文档元信息 -------------------------------------------------------
    title_src = meta["title_src"]
    if title_src is None:  # \title 通常在导言区
        tm = re.search(r"\\title\s*[*]?", src)
        if tm:
            r = tex._read_balanced(src, tex._skip_ws(src, tm.end()), "{", "}")
            title_src = r[0] if r else None
    title = tex.render(title_src)[0] if title_src else None
    if not title:
        title = next(
            (t.strip() for t, lv in zip(texts, heading_levels)
             if lv == 1 and t.strip()), None)
    if not title:
        title = Path(filename).stem

    char_offsets: list[int] = []
    cursor = 0
    for t in texts:
        char_offsets.append(cursor)
        cursor += len(t) + 1

    word_count = sum(
        len(re.findall(r"[\w一-鿿]+", t)) for t in texts)

    paragraphs = [
        Paragraph(id=p_ids[i], section_id=para_section[i], text=texts[i],
                  char_offset=char_offsets[i])
        for i in range(len(texts))
    ]

    return ParsedDocument(
        document=Document(
            title=title, filename=filename, source_format="tex",
            citation_style=style,  # type: ignore[arg-type]
            word_count=word_count,
        ),
        sections=sections,
        paragraphs=paragraphs,
        markers=markers,
        references=references,
    )
