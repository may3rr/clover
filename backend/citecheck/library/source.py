"""本地原文作为支持度证据来源，以及用封面元数据核验真实性。

A linked PDF replaces the network path for that reference: the excerpt
the judge sees is cut from the local full text (cover page and the
paper's own bibliography removed) with the same BM25 windowing as an
open-access PDF, and its metadata confirms or contradicts the entry.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from ..schema import Finding, RefCheck, Reference
from ..support.evidence import normalize_text
from ..support.sources import (
    _FULLTEXT_EXCERPT_LIMIT,
    SourceText,
    _bm25_excerpt,
    _drop_reference_tail,
)
from .link import _first_author_key
from .scan import LocalPdf
from .text import squash


def local_source(pdf: LocalPdf, claim_text: str) -> SourceText:
    if not pdf.doc.readable or not pdf.pages:
        return SourceText("none", None, pdf.doc.title)
    body, _ = pdf.body()
    body = _drop_reference_tail(body)
    if not body.strip():
        return SourceText("none", None, pdf.doc.title)
    excerpt = _bm25_excerpt(body, claim_text, _FULLTEXT_EXCERPT_LIMIT)
    return SourceText("fulltext", excerpt, pdf.doc.title)


def page_of(pdf: LocalPdf, evidence: str | None) -> int | None:
    """1-based page (as printed in the PDF viewer, cover pages included)
    where the evidence sits."""
    if not evidence:
        return None
    needle = normalize_text(evidence)[:60]
    for i, page in enumerate(pdf.pages):
        if needle and needle in normalize_text(page):
            return i + 1
    return None


# metadata is trusted for contradictions only when it came from the PDF's
# own text — a file name proves nothing
_TRUSTED = {"cnki_cover", "cnki_citation", "layout", "doi"}


def local_issues(ref: Reference, pdf: LocalPdf) -> list[str]:
    doc = pdf.doc
    if doc.source not in _TRUSTED:
        return []
    issues: list[str] = []
    if ref.title and doc.title and fuzz.ratio(squash(ref.title), squash(doc.title)) < 85:
        issues.append(f"本地原文标题为《{doc.title[:60]}》")
    want, have = _first_author_key(ref.authors), _first_author_key(doc.authors)
    if want and have and want != have and want not in squash(" ".join(doc.authors)):
        issues.append(f"本地原文首作者为 {doc.authors[0]}，文中写 {ref.authors[0]}")
    if ref.year and doc.year and abs(ref.year - doc.year) > 1:
        issues.append(f"本地原文年份为 {doc.year}，文中写 {ref.year}")
    return issues


def apply_local(ref: Reference, check: RefCheck, pdf: LocalPdf,
                para_len: int) -> tuple[RefCheck, Finding | None]:
    """Fold the linked PDF into a reference's verdict.

    Agreement turns "查不到" (unverifiable / not_found) into verified —
    the user holds the paper and its own pages name the same work.
    Disagreement is a mismatch, reported against the local copy. An
    online mismatch stands: the database record still disagrees.
    """
    from ..refs.verify import _finding

    issues = local_issues(ref, pdf)
    matched = dict(check.matched or {})
    matched.setdefault("title", pdf.doc.title)
    matched.update({"local_pdf": pdf.doc.id, "local_file": pdf.doc.filename,
                    "local_title": pdf.doc.title, "local_venue": pdf.doc.venue,
                    "local_year": pdf.doc.year})
    if issues:
        status = "mismatch"
        all_issues = (check.issues if check.status == "mismatch" else []) + issues
    elif check.status in {"unverifiable", "not_found"}:
        status, all_issues = "verified", []
        matched["verified_by"] = "local_pdf"
    else:
        status, all_issues = check.status, check.issues
    out = check.model_copy(update={"status": status, "issues": all_issues,
                                   "matched": matched})
    if status == "verified":
        return out, None
    finding = _finding(ref, out, para_len)
    if issues:
        finding.title = "文献信息与本地原文不一致"
        finding.detail = ("依据：" + "；".join(all_issues) + f"（本地文件：{pdf.doc.filename}）。\n"
                          "建议：核对参考文献条目，或确认文献文件夹中的 PDF 是否就是这篇文献。")
    return out, finding

