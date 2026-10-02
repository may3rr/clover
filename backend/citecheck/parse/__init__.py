from pathlib import Path

from .latex import parse_latex
from .parser import ParsedDocument, parse_docx


def parse_document(path: str | Path) -> ParsedDocument:
    """按输入类型分发：目录或 .tex 走 LaTeX 解析，其余走 docx。"""
    p = Path(path)
    if p.is_dir() or p.suffix.lower() == ".tex":
        return parse_latex(p)
    return parse_docx(p)


__all__ = ["parse_docx", "parse_latex", "parse_document", "ParsedDocument"]
