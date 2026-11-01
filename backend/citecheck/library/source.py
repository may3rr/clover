"""本地原文作为支持度证据来源，以及用封面元数据核验真实性。

A linked PDF replaces the network path for that reference: the excerpt
the judge sees is cut from the local full text (cover page and the
paper's own bibliography removed) with the same BM25 windowing as an
open-access PDF, and its metadata confirms or contradicts the entry.
"""

from __future__ import annotations

import re
import unicodedata

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
from .scan import LocalPdf, filename_meta
from .text import squash


def local_source(pdf: LocalPdf, claim_text: str, dense: bool = True) -> SourceText:
    if not pdf.doc.readable or not pdf.pages:
        return SourceText("none", None, pdf.doc.title)
    body, _ = pdf.body()
    body = _drop_reference_tail(body)
    if not body.strip():
        return SourceText("none", None, pdf.doc.title)
    excerpt = _bm25_excerpt(body, claim_text, _FULLTEXT_EXCERPT_LIMIT,
                            head=_HEAD_CHARS, dense=dense)
    return SourceText("fulltext", excerpt, pdf.doc.title)


def local_expanded(pdf: LocalPdf, query: str, dense: bool = True) -> str | None:
    """A larger excerpt for the review pass, ranked on ``query`` (the claim
    plus bilingual search terms): the first excerpt often misses the
    passage that holds the detail a partial verdict says is absent."""
    if not pdf.doc.readable or not pdf.pages:
        return None
    body = _drop_reference_tail(pdf.body()[0])
    if not body.strip():
        return None
    return _bm25_excerpt(body, query, _REVIEW_EXCERPT_LIMIT, head=_HEAD_CHARS,
                         max_parts=12, dense=dense)


_REVIEW_EXCERPT_LIMIT = 6000

# opening of the paper put ahead of the BM25 windows: title, authors and
# the abstract tell the judge which work it is reading
_HEAD_CHARS = 600


def local_title(pdf: LocalPdf, matched: dict | None, ref: Reference | None) -> str | None:
    """Title shown to the judge for a linked PDF. The largest-font line is
    the title for most papers, but an arXiv side stamp or a broken font
    map yields something that names no paper; then the verified record's
    title, then the manuscript entry's, stand in."""
    t = pdf.doc.title
    if t and _legible(t) and not t.lower().startswith("arxiv:") and len(t) >= 8:
        return t
    return (matched or {}).get("title") or (ref.title if ref else None) or t


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


_CJK_RE = re.compile(r"[一-鿿]")


def _is_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _legible(text: str) -> bool:
    """A title extracted with a broken font map comes out as symbol soup
    ("„ØÓÚ¨¸»œ¶Ô»°"); it says nothing about which paper this is."""
    t = re.sub(r"\s+", "", text or "")
    return bool(t) and len(squash(t)) / len(t) >= 0.6


# what a PDF's metadata or a file-name suffix puts where no author was given
_PLACEHOLDER = re.compile(r"^(anon(ymous)?|unknown|author|admin|user)s?$")

_SPACING_ACCENT = re.compile(r"(?<=\w)[´¨ˆ˜`˝˚ˇ](?=\w)")


def _fold(names: list[str]) -> list[str]:
    """Drop diacritics so 'Gonz´alez' (a PDF-extracted spacing accent)
    and 'González' compare equal."""
    out = []
    for n in names:
        n = _SPACING_ACCENT.sub("", n or "")
        n = unicodedata.normalize("NFKD", n)
        out.append("".join(c for c in n if not unicodedata.combining(c)))
    return out


def _name_tokens(name: str) -> set[str]:
    return {squash(t) for t in re.split(r"[\s,.]+", name) if len(t) >= 2}


def _title_on_page(ref_title: str, pdf_title: str, pdf: LocalPdf) -> bool:
    """The largest-font text on page 1 is a figure label or a teaser
    caption for some papers ("inference time (ms)", "0.95 0.80"), and an
    entry may cite the short form of a title with a subtitle ("The Open
    Images Dataset V4"). Either way the entry's title printed on the
    opening pages, or the extracted title being the start of the entry's,
    means the PDF names the same work."""
    want = squash(ref_title)
    if len(want) < 12:
        return False
    have = squash(pdf_title)
    if len(have) >= 12 and want.startswith(have):
        return True
    head = squash(pdf.first_pages)[:6000]
    return want in head or fuzz.partial_ratio(want, head) >= 92


def local_issues(ref: Reference, pdf: LocalPdf) -> list[str]:
    doc = pdf.doc
    if doc.source not in _TRUSTED:
        return []
    issues: list[str] = []
    # a pinyin / English rendering of a Chinese paper ("Yu Kai", an English
    # title) cannot be compared character by character with the cover
    # page — the link already matched them, so silence is the honest call
    if (ref.title and doc.title and _legible(doc.title)
            and _is_cjk(ref.title) == _is_cjk(doc.title)
            and fuzz.ratio(squash(ref.title), squash(doc.title)) < 85
            and not _title_on_page(ref.title, doc.title, pdf)):
        issues.append(f"本地原文标题为《{doc.title[:60]}》")
    # a file name suffix ("_González.pdf", "_anon.pdf") fills in the
    # authors when the page gave none; it proves nothing about the paper
    _, fn_author = filename_meta(doc.filename)
    from_name = bool(fn_author) and doc.authors == [fn_author]
    want = _first_author_key(_fold(ref.authors))
    have = _first_author_key(_fold(doc.authors))
    on_page = squash(" ".join(_fold(doc.authors)))
    # "Ling Xiao" / "Yang M Q": the order heuristic may take the given name
    # as the surname; any full-name token of the entry's first author found
    # among the page's authors is the same person
    page_tokens = set().union(*(_name_tokens(n) for n in _fold(doc.authors[:6])))
    tokens = _name_tokens(_fold(ref.authors[:1])[0]) if ref.authors else set()
    if (want and have and not from_name and not _PLACEHOLDER.match(have)
            and _is_cjk(want) == _is_cjk(have)
            and want != have and want not in on_page
            and not (tokens & page_tokens)):
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
                    "local_authors": pdf.doc.authors[:4],
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

