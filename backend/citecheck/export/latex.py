"""导出批注版 LaTeX 项目（.zip）。

LaTeX 没有 Word 那样的批注与修订，这里用两种同样可撤销的形式对应：

- **批注**：每条问题写成 ``%`` 注释行，插在锚点所在源码行的上方（.bib
  条目则插在 ``@entry`` 上方）。整行注释不改变排版结果，删掉即复原；
  没有锚点的全文问题集中写在主文件开头。
- **修订**：错别字修正不直接改源码，而是生成 ``clover-revisions.patch``
  （统一 diff 格式，针对导出后的文件），作者可在编辑器里逐块审阅，或
  用 ``git apply clover-revisions.patch`` 一次接受。无法逐字定位的修订
  退化为注释里的修改建议。

原项目（文件夹 / 压缩包 / .tex）只读不改，结果写成新的 zip。
"""

from __future__ import annotations

import difflib
import os
import tempfile
import zipfile
from pathlib import Path

from ..parse import parse_document
from ..parse.latex.archive import archive_stem, is_archive
from ..parse.latex.locate import Locator
from ..schema import Report

_SEVERITY = {"high": "高", "medium": "中", "low": "低"}
_LAYER = {"authenticity": "文献真实性", "support": "论断支持度",
          "distribution": "引用分布", "norms": "格式规范"}
_SKIP_DIRS = {"__MACOSX", ".git", "node_modules"}
_MARKER = ".clover-extracted"
PATCH_NAME = "clover-revisions.patch"


class LatexExportError(RuntimeError):
    pass


def default_out(src: Path) -> Path:
    directory = src.parent
    tmp = Path(tempfile.gettempdir()).resolve()
    try:
        src.resolve().relative_to(tmp)
        directory = Path.home() / "Downloads"  # 上传的副本 → 下载目录
    except ValueError:
        pass
    stem = archive_stem(src) if is_archive(src) else (
        src.name if src.is_dir() else src.stem)
    for k in range(1, 1000):
        suffix = "（Clover）" if k == 1 else f"（Clover {k}）"
        cand = directory / f"{stem}{suffix}.zip"
        if not cand.exists():
            return cand
    raise LatexExportError("无法生成输出文件名")


def _comment_lines(head: str, detail: str) -> list[str]:
    lines = [head] + [ln.strip() for ln in detail.splitlines() if ln.strip()]
    # .bib 中 @ 会被当成条目起点；注释里换成全角
    return ["% " + ln.replace("@", "＠") for ln in lines]


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _encode(text: str, enc: str, had_bom: bool) -> bytes:
    if enc == "latin-1":
        return text.encode("latin-1", errors="xmlcharrefreplace")
    data = text.encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if had_bom else data


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, max(pos, 0)) + 1


def _insert_comments(text: str, notes: dict[int, list[str]]) -> str:
    """notes：行首偏移 → 注释行。从后往前插，偏移不漂移。"""
    out = text
    for at in sorted(notes, reverse=True):
        # 与目标行同缩进，读起来贴着那一行
        j = at
        while j < len(out) and out[j] in " \t":
            j += 1
        indent = out[at:j]
        block = "".join(f"{indent}{ln}\n" for ln in notes[at])
        out = out[:at] + block + out[at:]
    return out


def export_latex(
    src_path: str | Path,
    report: Report,
    out_path: str | Path | None = None,
    author: str | None = None,
) -> Path:
    src = Path(src_path)
    parsed = parse_document(src)
    lmap = parsed.latex
    if lmap is None:
        raise LatexExportError("这不是 LaTeX 项目，无法导出批注版源码。")
    # 锚点按段落文本偏移换算；源码在体检之后被改过时偏移不再可信
    now = {p.id: p.text for p in parsed.paragraphs}
    if any(now.get(p.id) != p.text for p in report.paragraphs):
        raise LatexExportError(
            "源码在体检之后有改动，批注位置已对不上。请重新体检这篇论文后再导出。")

    root = Path(lmap.root)
    who = (author or "Clover").strip() or "Clover"
    loc = Locator(lmap)

    # ---- 收集批注 ---------------------------------------------------------
    notes: dict[str, dict[int, list[str]]] = {}
    general: list[str] = []
    for f in report.findings:
        head = (f"{who} 批注（{_LAYER.get(f.layer, f.layer)}，"
                f"{_SEVERITY.get(f.severity, f.severity)}）：{f.title}")
        lines = _comment_lines(head, f.detail)
        hit = loc.offset(f.anchor.paragraph_id, f.anchor.start) \
            if f.anchor else None
        sf = loc.file(hit[0]) if hit else None
        if hit is None or sf is None:
            general += lines
            continue
        at = _line_start(sf.text, hit[1])
        notes.setdefault(hit[0], {}).setdefault(at, []).extend(lines)

    # ---- 修订：逐字定位成功的进 patch，其余进注释 -----------------------
    edits: dict[str, list[tuple[int, int, str]]] = {}
    for r in report.revisions:
        a = loc.offset(r.anchor.paragraph_id, r.anchor.start)
        b = loc.offset(r.anchor.paragraph_id, max(r.anchor.end - 1, r.anchor.start))
        sf = loc.file(a[0]) if a else None
        ok = (a and b and sf and a[2] and b[2] and a[0] == b[0]
              and sf.text[a[1]: b[1] + 1] == r.old)
        if ok:
            edits.setdefault(a[0], []).append((a[1], b[1] + 1, r.new))
            continue
        lines = _comment_lines(
            f"{who} 修订建议：「{r.old}」改为「{r.new}」", r.reason)
        if a and sf:
            at = _line_start(sf.text, a[1])
            notes.setdefault(a[0], {}).setdefault(at, []).extend(lines)
        else:
            general += lines

    if general:
        main = lmap.main
        intro = [f"% {who} 体检：以下问题针对全文，没有对应到具体位置。"]
        notes.setdefault(main, {}).setdefault(0, [])
        notes[main][0] = intro + general + ["%"] + notes[main][0]

    # ---- 生成文件 ---------------------------------------------------------
    touched = set(notes) | set(edits)
    annotated: dict[str, bytes] = {}
    patch_parts: list[str] = []
    for rel in sorted(touched):
        raw = (root / rel).read_bytes()
        text, enc = _decode(raw)
        had_bom = raw.startswith(b"\xef\xbb\xbf")
        # 先在原文上应用修订得到"接受后"的版本，再给两份都插同样的批注：
        # patch 是 批注版 → 批注版+修订，对导出的文件直接可用
        fixed = text
        file_edits = edits.get(rel, [])
        for s, e, new in sorted(file_edits, reverse=True):
            fixed = fixed[:s] + new + fixed[e:]
        file_notes = notes.get(rel, {})
        out_text = _insert_comments(text, file_notes)
        annotated[rel] = _encode(out_text, enc, had_bom)
        if file_edits:
            fixed_notes = _shift_notes(file_notes, file_edits)
            fixed_text = _insert_comments(fixed, fixed_notes)
            patch_parts += difflib.unified_diff(
                out_text.splitlines(keepends=True),
                fixed_text.splitlines(keepends=True),
                fromfile=f"a/{rel}", tofile=f"b/{rel}", n=2)

    out = Path(out_path) if out_path else default_out(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, path in _project_files(src, root, lmap.files):
            if rel in annotated:
                zf.writestr(rel, annotated[rel])
            else:
                zf.write(path, rel)
        if patch_parts:
            zf.writestr(PATCH_NAME, "".join(patch_parts))
    tmp.replace(out)
    return out


def _shift_notes(notes: dict[int, list[str]],
                 edits: list[tuple[int, int, str]]) -> dict[int, list[str]]:
    """修订改变了行内长度：把行首偏移换算到修订后的文本。"""
    out: dict[int, list[str]] = {}
    for at, lines in notes.items():
        delta = sum(len(new) - (e - s) for s, e, new in edits if e <= at)
        out[at + delta] = lines
    return out


def _project_files(src: Path, root: Path, used: list[str]):
    """要打包的文件：文件夹与压缩包导出整个项目；单个 .tex 只导出
    解析时用到的源文件（不把所在目录的无关文件卷进去）。"""
    if src.is_file() and not is_archive(src):
        for rel in used:
            p = root / rel
            if p.is_file():
                yield rel, p
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name == _MARKER or name.startswith("."):
                continue
            p = Path(dirpath) / name
            yield p.relative_to(root).as_posix(), p
