"""中文期刊对标：用文献文件夹里的同刊范文现场建基线。

There is no arXiv for Chinese journals, and scraping CNKI is not an
option. The author's own folder usually holds recent papers of the
journal they are submitting to (the PDFs that are not cited). Their
statistics, computed locally, become the benchmark:

- the same section metrics as the arXiv benchmark (citation share and
  density per canonical section, citations per sentence), so the
  distribution layer compares them unchanged;
- journal-level indicators Chinese editors look at: reference count,
  share of references from the last three years, share of foreign
  references, structured-abstract length, figures and tables.

Each exemplar's profile is cached by file hash. The result is a
benchmark dict in the arxiv_cs_cl.json shape plus ``venue_stats``.
"""

from __future__ import annotations

import logging
import re
import statistics
from datetime import date

from ..cache import Cache
from ..library.scan import LocalPdf
from ..library.text import clean_page, squash_cjk_spaces
from ..parse.headings import canonical_for
from ..parse.parser import ParsedDocument
from ..refs.structure import parse_reference
from ..support.claims import split_sentences

log = logging.getLogger(__name__)

MIN_EXEMPLARS = 5
_VERSION = "2"
CANONICALS = ["intro", "related", "method", "experiment", "discussion",
              "conclusion", "other"]

_HEADING_RE = re.compile(r"^(\d{1,2})\s*([一-鿿A-Za-z][^。；;，,：:]{1,28})$")
_REF_HEAD_RE = re.compile(r"^(参考文献|References)\s*[:：]?$", re.I)
_BACK_RE = re.compile(r"^(作者贡献声明|利益冲突声明|支撑数据|通讯作者|收稿日期)")
_MARKER_RE = re.compile(r"\[(\d{1,3}(?:\s*[-–,，]\s*\d{1,3})*)\]")
_ENTRY_RE = re.compile(r"\[(\d{1,3})\]\s*")
_CJK = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]+(?:['’-][A-Za-zÀ-ɏ]+)*")

# label, unit for the journal-level indicators (manuscript vs exemplars)
VENUE_STATS: dict[str, tuple[str, str]] = {
    "n_refs": ("参考文献数量", "条"),
    "recent_share": ("近三年文献占比", "%"),
    "foreign_share": ("外文文献占比", "%"),
    "abstract_chars": ("中文摘要字数", "字"),
    "n_figures": ("图", "幅"),
    "n_tables": ("表", "张"),
}


def _words(text: str) -> int:
    return len(_LATIN.findall(text)) + len(_CJK.findall(text))


def _items(raw: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"[,，]", raw):
        m = re.match(r"\s*(\d+)\s*[-–]\s*(\d+)\s*$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out += list(range(a, b + 1)) if 0 < b - a < 50 else [a, b]
        elif part.strip().isdigit():
            out.append(int(part))
    return out


def _lines(pdf: LocalPdf) -> list[str]:
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(pdf.path))
    out: list[str] = []
    for page in reader.pages[pdf.cover_pages:]:
        for ln in (page.extract_text() or "").split("\n"):
            # typeset pages space brackets out: "[ 1 ]", "[ J ]"
            ln = re.sub(r"\[\s*([\dA-Z/,，\-–\s]{1,20}?)\s*\]",
                        lambda m: "[" + re.sub(r"\s+", "", m.group(1)) + "]",
                        squash_cjk_spaces(ln)).strip()
            if ln:
                out.append(ln)
    return out


def _recent_share(years: list[int], pub_year: int) -> float | None:
    if not years:
        return None
    return sum(1 for y in years if y >= pub_year - 2) / len(years)


def profile_pdf(pdf: LocalPdf) -> dict | None:
    """One exemplar's statistics, or None when its structure can't be
    read (no numbered headings or no reference list)."""
    lines = _lines(pdf)
    ref_at = max((i for i, ln in enumerate(lines) if _REF_HEAD_RE.match(ln)), default=None)
    if ref_at is None:
        return None
    body, tail = lines[:ref_at], lines[ref_at + 1:]
    end = next((i for i, ln in enumerate(tail) if _BACK_RE.match(ln)), len(tail))
    ref_text = clean_page("\n".join(tail[:end]))

    # sections: top-level numbered headings in sequence 1, 2, 3 …
    sections: list[tuple[str, list[str]]] = []
    expect = 1
    for ln in body:
        m = _HEADING_RE.match(ln)
        # one missed heading (a garbled line) must not end the sequence
        if (m and int(m.group(1)) in (expect, expect + 1) and sections or
                m and int(m.group(1)) == 1 and not sections) \
                and not re.search(r"\d{3,}", m.group(2)):
            sections.append((canonical_for(m.group(2)), []))
            expect = int(m.group(1)) + 1
        elif sections:
            sections[-1][1].append(ln)
    if len(sections) < 3:
        return None

    sec_cites: dict[str, int] = {}
    sec_words: dict[str, int] = {}
    sentence_counts: list[int] = []
    for canon, sec_lines in sections:
        text = clean_page("\n".join(sec_lines))
        n = sum(len(_items(m.group(1))) for m in _MARKER_RE.finditer(text))
        sec_cites[canon] = sec_cites.get(canon, 0) + n
        sec_words[canon] = sec_words.get(canon, 0) + _words(text)
        for sent in split_sentences(text):
            ids = {i for m in _MARKER_RE.finditer(sent.text) for i in _items(m.group(1))}
            if ids:
                sentence_counts.append(len(ids))
    total = sum(sec_cites.values())
    if not total:
        return None

    entries = [e.strip() for e in _ENTRY_RE.split(ref_text)[2::2] if e.strip()]
    infos = [parse_reference(e) for e in entries]
    years = [i["year"] for i in infos if i["year"]]
    pub_year = pdf.doc.year or date.today().year
    head = clean_page("\n".join(lines[:80]))
    abstract = re.search(r"摘要\s*[:：](.+?)关键词", head)
    body_text = clean_page("\n".join(body))
    return {
        "sections": {c: {"cites": sec_cites[c], "words": sec_words[c]} for c in sec_cites},
        "total_cites": total,
        "sentence_counts": sentence_counts,
        "venue_stats": {
            "n_refs": len(entries),
            "recent_share": _recent_share(years, pub_year),
            "foreign_share": (sum(1 for i in infos if i["lang"] != "zh") / len(infos)) if infos else None,
            "abstract_chars": len(_CJK.findall(abstract.group(1))) if abstract else None,
            "n_figures": len(set(re.findall(r"图\s*(\d+)", body_text))),
            "n_tables": len(set(re.findall(r"表\s*(\d+)", body_text))),
        },
    }


def _q(vals: list[float]) -> dict | None:
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return None
    q1, med, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    return {"median": med, "q1": q1, "q3": q3}


def build_venue_benchmark(exemplars: list[LocalPdf], venue: str,
                          cache: Cache | None = None) -> dict | None:
    """Benchmark dict (arxiv_cs_cl.json shape + venue_stats) from the
    target journal's papers, or None with fewer than MIN_EXEMPLARS
    readable ones."""
    profiles = []
    for pdf in exemplars:
        key = f"venueprof|{_VERSION}|{pdf.doc.id}"
        prof = cache.get(key) if cache else None
        if prof is None:
            try:
                prof = profile_pdf(pdf) or {}
            except Exception as e:  # noqa: BLE001 — one bad PDF is skipped
                log.warning("venue profile failed for %s: %s", pdf.doc.filename, e)
                prof = {}
            if cache:
                cache.set(key, prof)
        if prof:
            profiles.append(prof)
    if len(profiles) < MIN_EXEMPLARS:
        return None

    sections: dict[str, dict] = {}
    for c in CANONICALS:
        shares = [p["sections"].get(c, {}).get("cites", 0) / p["total_cites"] for p in profiles]
        present = [p["sections"][c] for p in profiles if c in p["sections"]]
        dens = [s["cites"] * 1000 / s["words"] for s in present if s["words"]]
        sections[c] = {"share": _q(shares), "density_per_1k_words": _q(dens),
                       "present_in": len(present)}
        sections[c] = {k: v for k, v in sections[c].items() if v is not None}

    def share_ge(p, k):
        sc = p["sentence_counts"]
        return sum(1 for x in sc if x >= k) / len(sc) if sc else 0.0

    return {
        "id": f"venue:{venue}",
        "name": f"《{venue}》范文",
        "language": "zh",
        "n_papers": len(profiles),
        "sections": sections,
        "sentence_refs": {f"share_ge{k}": _q([share_ge(p, k) for p in profiles])
                          for k in (2, 3, 5)},
        "venue_stats": {k: _q([p["venue_stats"].get(k) for p in profiles])
                        for k in VENUE_STATS},
    }


def manuscript_stats(parsed: ParsedDocument, year: int | None = None) -> dict[str, float | None]:
    """The same journal-level indicators for the manuscript."""
    refs = [r for r in parsed.references if r.origin == "list"]
    years = [r.year for r in refs if r.year]
    text = "\n".join(p.text for p in parsed.paragraphs)
    abstract_sec = next((s for s in parsed.sections if s.title.strip().rstrip(":：") == "摘要"), None)
    abstract_chars = None
    if abstract_sec is not None:
        paras = [p.text for p in parsed.paragraphs if p.section_id == abstract_sec.id]
        abstract = "".join(t for t in paras if not re.match(r"(关键词|分类号|DOI)", t.strip()))
        abstract_chars = len(_CJK.findall(abstract))
    captions = "\n".join(p.text for p in parsed.paragraphs if p.caption) or text
    return {
        "n_refs": len(refs),
        "recent_share": _recent_share(years, year or date.today().year),
        "foreign_share": (sum(1 for r in refs if r.lang != "zh") / len(refs)) if refs else None,
        "abstract_chars": abstract_chars,
        "n_figures": len(set(re.findall(r"图\s*(\d+)", captions))),
        "n_tables": len(set(re.findall(r"表\s*(\d+)", captions))),
    }
