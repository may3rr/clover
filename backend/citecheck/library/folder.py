"""拖入的文件夹是什么：论文 + 文献文件夹，还是 LaTeX 项目。

Convention: the manuscript .docx sits at the folder root and the cited
PDFs in a ``ref/`` subfolder. Common variants are accepted too (refs,
references, 参考文献, 文献, pdf). A folder with .tex sources stays a LaTeX
project; a ``ref/`` next to them is still picked up as its library.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REF_DIR_NAMES = {"ref", "refs", "reference", "references", "参考文献", "文献",
                 "pdf", "pdfs", "papers", "literature"}
# Word lock files and our own exports are never the manuscript
_SKIP_DOCX = re.compile(r"^~\$|（引用体检|（Clover")
# names that mark a cover letter / response / diff rather than the paper
_SIDE_DOCX = re.compile(r"说明|对照|回复|修改|投稿信|cover|response|rebuttal|letter|diff", re.I)


@dataclass
class FolderLayout:
    paper: Path | None  # the .docx, or the folder itself for LaTeX
    library: Path | None  # folder holding the cited PDFs
    candidates: list[Path] = field(default_factory=list)  # other root .docx
    kind: str = "docx"  # docx | tex | unknown


def _pdf_count(d: Path) -> int:
    return sum(1 for p in d.rglob("*.pdf") if not p.name.startswith("."))


def find_library_dir(root: Path, allow_any: bool = False) -> Path | None:
    subdirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
    named = [d for d in subdirs
             if d.name.lower() in REF_DIR_NAMES or d.name.lower().endswith(" ref")]
    for d in named:
        if _pdf_count(d):
            return d
    if allow_any:
        with_pdfs = [d for d in subdirs if _pdf_count(d) >= 3]
        if len(with_pdfs) == 1:
            return with_pdfs[0]
    return None


def resolve_folder(path: str | Path) -> FolderLayout:
    root = Path(path)
    if not root.is_dir():
        return FolderLayout(paper=root, library=None, kind="file")
    docx = sorted(p for p in root.iterdir()
                  if p.is_file() and p.suffix.lower() == ".docx"
                  and not _SKIP_DOCX.search(p.name))
    has_tex = any(p.suffix.lower() == ".tex" for p in root.iterdir() if p.is_file())
    if has_tex and not docx:
        return FolderLayout(paper=root, library=find_library_dir(root), kind="tex")
    if not docx:
        return FolderLayout(paper=None, library=find_library_dir(root, True), kind="unknown")
    main = [p for p in docx if not _SIDE_DOCX.search(p.stem)] or docx
    # several plausible manuscripts: the most recently edited one first
    main.sort(key=lambda p: -p.stat().st_mtime)
    return FolderLayout(paper=main[0], library=find_library_dir(root, True),
                        candidates=[p for p in docx if p != main[0]], kind="docx")
