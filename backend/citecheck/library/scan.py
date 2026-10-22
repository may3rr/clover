"""文献库扫描：读一个文件夹里的 PDF，抽全文和元数据。

Metadata, most trusted first:
1. 知网网络首发封面 ("《X》网络首发论文 / 题目： / 作者： / 网络首发日期：")
2. 正式刊出页的「引用本文：」— a GB/T 7714 entry for the paper itself,
   parsed with the same parser as the manuscript's bibliography
3. DOI / arXiv id found on the first two pages
4. the largest-font text on page 1 (title), else PDF /Title metadata
5. the file name ("标题_作者.pdf" as CNKI names downloads)

Only PDFs are read; CAJ and scanned PDFs (no text layer) are listed as
unreadable, never OCR'd. Everything stays local. Results are cached by
file content hash, so a re-run of the same folder costs nothing.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..cache import Cache
from ..config import get_settings
from ..refs.structure import parse_reference
from ..schema import LibraryDoc
from .text import clean_page, squash, squash_cjk_spaces

log = logging.getLogger(__name__)

_MAX_PDF_BYTES = 80 * 1024 * 1024
_MIN_TEXT_CHARS = 200  # first three pages; less = scanned / image-only
_CACHE_VERSION = "5"

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>，。；)）\]]+)")
_DOI_LABEL_RE = re.compile(r"DOI\s*[:：]\s*(10\s*\.\s*\d{4,9}\s*/\s*[0-9a-z]+(?:\s*[./\-_]\s*[0-9a-z][0-9A-Za-z]*)*)")
# a DOI cut off right after the journal ISSN (unfinished online-first DOI)
_BARE_ISSN_DOI_RE = re.compile(r"\d{4}-\d{3}[\dX]\.?$")
_ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(v\d+)?", re.I)
_CNKI_COVER_RE = re.compile(r"《(?P<venue>[^》]+)》\s*网络首发论文")
_CNKI_FIELD_RE = re.compile(
    r"题目[:：]\s*(?P<title>.+?)\s*作者[:：]\s*(?P<authors>.+?)\s*"
    r"(?:收稿日期|网络首发日期)[:：]\s*(?P<year>(?:19|20)\d{2})", re.S)
_CITE_SELF_RE = re.compile(r"引用(?:本文|格式)\s*[:：]\s*(?P<entry>.{10,400}?\[J(?:/OL)?\].{0,200}?)(?=\(\s*[A-Z][a-z]|https?://|$)", re.S)
_DUP_SUFFIX_RE = re.compile(r"\s*[(（]\d+[)）]$")


@dataclass
class LocalPdf:
    """A scanned PDF: the report-facing record plus its text."""
    doc: LibraryDoc
    path: Path
    pages: list[str] = field(default_factory=list)  # cleaned, per page
    cover_pages: int = 0  # leading CNKI cover pages, not part of the paper

    @property
    def first_pages(self) -> str:
        return " ".join(self.pages[self.cover_pages:self.cover_pages + 2])

    def body(self) -> tuple[str, list[int]]:
        """Paper text without the CNKI cover, and each page's start offset
        in it (for "第 n 页" on evidence)."""
        starts: list[int] = []
        parts: list[str] = []
        pos = 0
        for p in self.pages[self.cover_pages:]:
            starts.append(pos)
            parts.append(p)
            pos += len(p) + 1
        return "\n".join(parts), starts


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _largest_text(page) -> str | None:
    """Text drawn in the largest font on a page — the title of most
    papers. Fragments too short to be a title (drop caps, logos) are
    skipped in favour of the next size down."""
    pieces: list[tuple[float, str]] = []

    def visit(text, cm, tm, _font, size):
        if not text or not text.strip():
            return
        scale = math.hypot(tm[2], tm[3]) * math.hypot(cm[2], cm[3])
        pieces.append((round(size * (scale or 1), 1), text))

    try:
        page.extract_text(visitor_text=visit)
    except Exception:  # noqa: BLE001
        return None
    for size in sorted({s for s, _ in pieces}, reverse=True)[:4]:
        text = squash_cjk_spaces(
            re.sub(r"\s+", " ", " ".join(t for s, t in pieces if s == size))).strip()
        if len(re.sub(r"\W", "", text)) >= 8 and len(text) <= 300:
            return text
    return None


def _find_doi(text: str) -> str | None:
    # typeset Chinese pages space the DOI out: "DOI : 10 . 11925 /infotech . 2096 - 3467 . 2025 . 0298"
    m = _DOI_LABEL_RE.search(text)
    if m:
        doi = re.sub(r"\s+", "", m.group(1)).rstrip(".,;")
        if _DOI_RE.fullmatch(doi) and not _BARE_ISSN_DOI_RE.search(doi):
            return doi
    m = _DOI_RE.search(text)
    if m and not _BARE_ISSN_DOI_RE.search(m.group(1).rstrip(".,;")):
        return m.group(1).rstrip(".,;")
    return None


def _filename_meta(name: str) -> tuple[str, str | None]:
    """(title guess, author guess) from a file name. CNKI saves downloads
    as "标题_第一作者.pdf"; browsers add " (1)" to repeats."""
    stem = _DUP_SUFFIX_RE.sub("", Path(name).stem).strip()
    if "_" in stem:
        title, author = stem.rsplit("_", 1)
        if 1 <= len(author) <= 30:
            return title.strip(), author.strip()
    return stem, None


def _meta_from_text(pages: list[str], raw_first: str) -> tuple[dict, int, str]:
    """(metadata, number of cover pages, provenance)."""
    head = unicodedata.normalize("NFKC", " ".join(pages[:3]))
    cover = _CNKI_COVER_RE.search(raw_first)
    if cover:
        flat = squash_cjk_spaces(re.sub(r"\s+", " ", raw_first))
        m = _CNKI_FIELD_RE.search(flat)
        if m:
            authors = [a.strip() for a in re.split(r"[,，、]", m["authors"]) if a.strip()]
            return ({"title": m["title"].strip(), "authors": authors,
                     "venue": cover["venue"].strip(), "year": int(m["year"]),
                     "doi": None}, 1, "cnki_cover")
    m = _CITE_SELF_RE.search(head)
    if m:
        info = parse_reference(m["entry"])
        if info["title"] and info["authors"]:
            return ({k: info[k] for k in ("title", "authors", "venue", "year", "doi")},
                    0, "cnki_citation")
    return ({}, 0, "")


def _read(path: Path) -> tuple[list[str], str, str | None, str | None]:
    """(clean pages, raw first page, largest-font title, /Title)."""
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(path))
    raw_pages = [(p.extract_text() or "") for p in reader.pages]
    big = _largest_text(reader.pages[0]) if reader.pages else None
    meta_title = None
    try:
        meta_title = (reader.metadata or {}).get("/Title")
    except Exception:  # noqa: BLE001
        pass
    return ([clean_page(t) for t in raw_pages], raw_pages[0] if raw_pages else "",
            big, str(meta_title) if meta_title else None)


def _scan_one(path: Path, sha: str, cache: Cache) -> LocalPdf:
    key = f"libpdf|{_CACHE_VERSION}|{sha}"
    hit = cache.get(key)
    if hit is not None:
        return LocalPdf(LibraryDoc.model_validate(hit["doc"]).model_copy(
            update={"filename": path.name}), path, hit["pages"], hit["cover"])

    fn_title, fn_author = _filename_meta(path.name)
    doc = LibraryDoc(id=sha[:16], filename=path.name)
    pages: list[str] = []
    cover = 0
    try:
        if path.stat().st_size > _MAX_PDF_BYTES:
            raise ValueError("too large")
        pages, raw_first, big, meta_title = _read(path)
    except Exception as e:  # noqa: BLE001 — encrypted, truncated, not a PDF
        log.warning("library: cannot read %s: %s", path.name, e)
        doc.readable = False
        doc.title, doc.authors, doc.source = fn_title, [fn_author] if fn_author else [], "filename"
        return LocalPdf(doc, path)

    doc.pages = len(pages)
    if sum(len(p) for p in pages[:3]) < _MIN_TEXT_CHARS:
        doc.readable = False

    meta, cover, source = _meta_from_text(pages, raw_first)
    head = " ".join(pages[cover:cover + 2])
    doi = _find_doi(head)
    if doi and not meta.get("doi"):
        meta["doi"] = doi
    arxiv = _ARXIV_RE.search(head)
    if arxiv:
        doc.arxiv_id = arxiv.group(1)
    if not meta.get("title"):
        text_key = squash(" ".join(pages[:3]))
        # broken font maps produce a "largest text" that is not in the
        # extracted text at all — fall back to the file name then
        title = big if big and squash(big) in text_key else None
        if not title and meta_title and len(meta_title) > 8 and not re.match(
                r"(?i)microsoft word|untitled|\S+\.(docx?|pdf|tex)$", meta_title):
            title = meta_title
        if title:
            meta["title"], source = title, "layout"
        else:
            meta["title"], source = fn_title, "filename"
        if not meta.get("authors") and fn_author:
            meta["authors"] = [fn_author]
        if not meta.get("year") and doc.arxiv_id:
            meta["year"] = 2000 + int(doc.arxiv_id[:2])
    for k in ("title", "authors", "venue", "year", "doi"):
        if meta.get(k):
            setattr(doc, k, meta[k])
    doc.source = source or ("doi" if doc.doi else "filename")
    cache.set(key, {"doc": doc.model_dump(), "pages": pages, "cover": cover})
    return LocalPdf(doc, path, pages, cover)


def list_pdfs(folder: str | Path) -> list[Path]:
    root = Path(folder)
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() == ".pdf"
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def unsupported_files(folder: str | Path) -> list[str]:
    """CAJ / KDH / NH files the user may expect us to read."""
    root = Path(folder)
    return sorted(p.name for p in root.rglob("*")
                  if p.is_file() and p.suffix.lower() in {".caj", ".kdh", ".nh"})


def scan_folder(folder: str | Path, cache: Cache | None = None,
                progress=None) -> list[LocalPdf]:
    """Every distinct PDF under ``folder`` (byte-identical copies are
    merged into one entry with ``duplicates``)."""
    cache = cache or Cache(get_settings().cache_path)
    paths = list_pdfs(folder)
    by_sha: dict[str, list[Path]] = {}
    for p in paths:
        by_sha.setdefault(_sha256(p), []).append(p)
    # keep the copy without a " (1)" suffix as the representative
    groups = [(sha, sorted(ps, key=lambda p: (bool(_DUP_SUFFIX_RE.search(p.stem)), len(p.name))))
              for sha, ps in by_sha.items()]

    done = 0

    def work(item):
        nonlocal done
        sha, ps = item
        pdf = _scan_one(ps[0], sha, cache)
        pdf.doc.duplicates = [p.name for p in ps[1:]]
        done += 1
        if progress is not None:
            progress(done, len(groups))
        return pdf

    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(work, groups))
    return sorted(out, key=lambda p: p.doc.filename)
