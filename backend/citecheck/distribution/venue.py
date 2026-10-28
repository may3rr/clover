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

A profile also keeps what each number is read from — the page of every
section heading, the citing sentences, the reference list, the captions
and the abstract — so the report can point at the exact place in each
exemplar (venue_metrics.py), and the model reads (venue_model.py) work
on the same text. Each exemplar's profile is cached by file hash. The
benchmark dict has the arxiv_cs_cl.json shape plus ``venue_stats``.
"""

from __future__ import annotations

import logging
import re
import statistics
from datetime import date

from ..cache import Cache
from ..library.scan import LocalPdf
from ..library.text import clean_page, squash_cjk_spaces
from ..library.venue_match import paper_type
from ..parse.headings import canonical_for
from ..parse.parser import ParsedDocument
from ..refs.structure import parse_reference
from ..support.claims import split_sentences

log = logging.getLogger(__name__)

MIN_EXEMPLARS = 5
_VERSION = "3"
CANONICALS = ["intro", "related", "method", "experiment", "discussion",
              "conclusion", "other"]

# "1 引言" / "3.研究方法" / "3两种任务情境下的多维量化评估：性别表征失衡测度"
# (a measure word after the number is a sentence: "5个维度…")
_HEADING_RE = re.compile(
    r"^(\d{1,2})(\s*[.．、](?!\d))?\s*(?![个种项类篇条次名位家年月日倍层步轮维])"
    r"([一-鿿A-Za-z][^。；;，,]{1,40})$")
_REF_HEAD_RE = re.compile(r"^(参考文献|References)\s*[:：]?$", re.I)
_BACK_RE = re.compile(r"^(作者贡献声明|利益冲突声明|支撑数据|通讯作者|收稿日期)")
_MARKER_RE = re.compile(r"\[(\d{1,3}(?:\s*[-–,，]\s*\d{1,3})*)\]")
_ENTRY_RE = re.compile(r"\[(\d{1,3})\]\s*")
_CAPTION_RE = re.compile(r"^(图|表|Fig(?:ure)?\.?|Table)\s*(\d{1,2})(?![\d.．])\s*(.{0,60})", re.I)
_CJK = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]+(?:['’-][A-Za-zÀ-ɏ]+)*")
_SENT_MAX = 400

# label, unit for the journal-level indicators (manuscript vs exemplars)
VENUE_STATS: dict[str, tuple[str, str]] = {
    "n_refs": ("参考文献数量", "条"),
    "recent_share": ("近三年文献占比", "%"),
    "foreign_share": ("外文文献占比", "%"),
    "abstract_chars": ("中文摘要字数", "字"),
    "n_figures": ("图", "幅"),
    "n_tables": ("表", "张"),
}

# GB/T 7714 document type codes -> the buckets the report compares
_TYPE_CODE = re.compile(r"\[\s*(J|C|A|M|D|R|P|S|N|Z|G|EB|DB|CP)\s*(?:/\s*OL)?\s*\]", re.I)
_CODE_TYPE = {"J": "journal", "C": "conference", "A": "conference", "M": "book",
              "G": "book", "D": "thesis", "EB": "web", "DB": "web", "CP": "web"}
_PREPRINT = re.compile(r"arxiv|corr\b|preprint|biorxiv|medrxiv|openreview", re.I)
_CONF = re.compile(r"proceedings|conference|workshop|symposium|\bin:|\bacl\b|emnlp|naacl|"
                   r"neurips|nips\b|icml|iclr|aaai|ijcai|coling|sigir|kdd|cvpr|iccv|"
                   r"会议|论文集", re.I)
_JOURNAL = re.compile(r"journal|transactions|\bvol\.|\d+\s*\(\s*\d+\s*\)\s*[:：]|学报|期刊", re.I)
_WEB = re.compile(r"https?://", re.I)
REF_TYPES = ["journal", "conference", "preprint", "book", "thesis", "web"]


def ref_type(raw: str) -> str:
    """journal | conference | preprint | book | thesis | web | other: the
    GB/T 7714 code when there is one, else the venue's wording."""
    if _PREPRINT.search(raw):
        return "preprint"
    m = _TYPE_CODE.search(raw)
    if m:
        return _CODE_TYPE.get(m.group(1).upper(), "other")
    if _CONF.search(raw):
        return "conference"
    if _JOURNAL.search(raw):
        return "journal"
    if _WEB.search(raw):
        return "web"
    return "other"


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


def _lines(pdf: LocalPdf) -> list[tuple[str, int]]:
    """(line, 1-based page in the PDF) for the paper without its cover."""
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(pdf.path))
    out: list[tuple[str, int]] = []
    for i, page in enumerate(reader.pages[pdf.cover_pages:], pdf.cover_pages + 1):
        for ln in (page.extract_text() or "").split("\n"):
            # typeset pages space brackets out: "[ 1 ]", "[ J ]"
            ln = re.sub(r"\[\s*([\dA-Z/,，\-–\s]{1,20}?)\s*\]",
                        lambda m: "[" + re.sub(r"\s+", "", m.group(1)) + "]",
                        squash_cjk_spaces(ln)).strip()
            if ln:
                out.append((ln, i))
    return out


def _recent_share(years: list[int], pub_year: int) -> float | None:
    if not years:
        return None
    return sum(1 for y in years if y >= pub_year - 2) / len(years)


def _heading_ok(title: str, zh: bool) -> bool:
    """A numbered line is a section heading, not a table row or an
    example sentence ("5 e- 5", "5 Wondering", "5 is the last")."""
    if re.search(r"\d{3,}", title):
        return False
    if canonical_for(title) != "other":
        return True
    if zh:
        return len(_CJK.findall(title)) >= 2
    words = title.split()
    return title[0].isupper() and 2 <= len(words) <= 10 and not title.endswith(".")


def _pages_of(lines: list[tuple[str, int]]) -> list[int]:
    return [p for _, p in lines]


def _join(lines: list[tuple[str, int]]) -> str:
    return clean_page("\n".join(ln for ln, _ in lines))


def profile_pdf(pdf: LocalPdf) -> dict | None:
    """One exemplar's statistics and their sources, or None when its
    structure can't be read (no numbered headings or no reference list)."""
    lines = _lines(pdf)
    ref_at = max((i for i, (ln, _) in enumerate(lines) if _REF_HEAD_RE.match(ln)), default=None)
    if ref_at is None:
        return None
    body, tail = lines[:ref_at], lines[ref_at + 1:]
    end = next((i for i, (ln, _) in enumerate(tail) if _BACK_RE.match(ln)), len(tail))
    ref_text = _join(tail[:end])
    sample = " ".join(ln for ln, _ in body[:300])
    zh = len(_CJK.findall(sample)) > len(_LATIN.findall(sample))

    # sections: top-level numbered headings in sequence 1, 2, 3 …
    heads: list[dict] = []
    sec_lines: list[list[tuple[str, int]]] = []
    expect = 1
    body_start = None
    dotted = None  # "1. 引言" or "1 引言": numbered lists use the other style
    for k, (ln, page) in enumerate(body):
        m = _HEADING_RE.match(ln)
        n = int(m.group(1)) if m else 0
        # one missed heading (a garbled line) must not end the sequence
        if m and (n in (expect, expect + 1) and heads or n == 1 and not heads) \
                and (dotted is None or bool(m.group(2)) == dotted
                     or canonical_for(m.group(3)) != "other") \
                and _heading_ok(m.group(3).strip(), zh):
            title = m.group(3).strip()
            dotted = bool(m.group(2)) if dotted is None else dotted
            heads.append({"num": n, "title": title, "canonical": canonical_for(title),
                          "page": page})
            sec_lines.append([])
            expect = n + 1
            if body_start is None:
                body_start = k
        elif heads:
            sec_lines[-1].append((ln, page))
    if len(heads) < 3:
        return None

    sentences: list[dict] = []
    for h, sl in zip(heads, sec_lines):
        text = _join(sl)
        h["cites"] = sum(len(_items(m.group(1))) for m in _MARKER_RE.finditer(text))
        h["markers"] = len(_MARKER_RE.findall(text))
        h["words"] = _words(text)
        # page of each citing sentence: the page its first marker sits on
        marker_pages = [p for ln, p in sl for _ in _MARKER_RE.finditer(ln)]
        mk = 0
        for sent in split_sentences(text):
            ms = list(_MARKER_RE.finditer(sent.text))
            if not ms:
                continue
            ids = {i for m in ms for i in _items(m.group(1))}
            sentences.append({"text": sent.text.strip()[:_SENT_MAX], "ids": len(ids),
                              "page": marker_pages[min(mk, len(marker_pages) - 1)]
                              if marker_pages else h["page"], "section": h["canonical"]})
            mk += len(ms)
    total = sum(h["cites"] for h in heads)
    if not total:
        return None

    entries = [e.strip() for e in _ENTRY_RE.split(ref_text)[2::2] if e.strip()]
    infos = [parse_reference(e) for e in entries]
    pub_year = pdf.doc.year or date.today().year
    years = [i["year"] for i in infos if i["year"] and i["year"] <= pub_year + 1]

    front = body[:body_start or 0] or lines[:80]
    head_text = _join(front)
    abstract = re.search(r"摘\s*要\s*[:：](.+?)关键词", head_text)
    abstract_txt = abstract.group(1).strip() if abstract else None
    abstract_page = next((p for ln, p in front if "摘" in ln and "要" in ln), None)
    # a structured abstract shorter than this was not read whole
    if abstract_txt and len(_CJK.findall(abstract_txt)) < 120:
        abstract_txt = None

    captions: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ln, page in body:
        m = _CAPTION_RE.match(ln)
        if not m:
            continue
        kind = "fig" if m.group(1).lower().startswith(("图", "fig")) else "tab"
        rest = m.group(3).strip()
        # a caption names something; "图1所示" / "表2中" continue a sentence
        if not rest or re.match(r"^(所示|中|给出|展示|可见|为|是|和|与|的|,|，|。|列出)", rest):
            continue
        if (kind, m.group(2)) in seen:
            continue
        seen.add((kind, m.group(2)))
        captions.append({"kind": kind, "num": m.group(2), "text": ln[:80], "page": page})
    body_text = _join(body)
    figs_mentioned = len(set(re.findall(r"图\s*(\d+)", body_text)))
    tabs_mentioned = len(set(re.findall(r"表\s*(\d+)", body_text)))
    n_fig = sum(1 for c in captions if c["kind"] == "fig") or figs_mentioned
    n_tab = sum(1 for c in captions if c["kind"] == "tab") or tabs_mentioned

    sections: dict[str, dict] = {}
    for h in heads:
        s = sections.setdefault(h["canonical"], {"cites": 0, "words": 0, "markers": 0,
                                                 "page": h["page"], "title": h["title"]})
        s["cites"] += h["cites"]
        s["words"] += h["words"]
        s["markers"] += h["markers"]
    types = [ref_type(e) for e in entries]
    return {
        "version": _VERSION,
        "title": pdf.doc.title,
        "year": pub_year,
        "paper_type": paper_type(pdf.doc.title),
        "headings": heads,
        "sections": sections,
        "total_cites": total,
        "sentence_counts": [s["ids"] for s in sentences],
        "sentences": sentences,
        "words": sum(h["words"] for h in heads),
        "ref_page": lines[ref_at][1],
        "ref_years": years,
        "ref_types": types,
        "abstract": abstract_txt,
        "abstract_page": abstract_page,
        "captions": captions,
        "venue_stats": {
            "n_refs": len(entries),
            "recent_share": _recent_share(years, pub_year),
            "foreign_share": (sum(1 for i in infos if i["lang"] != "zh") / len(infos)) if infos else None,
            "abstract_chars": len(_CJK.findall(abstract_txt)) if abstract_txt else None,
            "n_figures": n_fig,
            "n_tables": n_tab,
        },
    }


def _q(vals: list[float]) -> dict | None:
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return None
    q1, med, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    return {"median": med, "q1": q1, "q3": q3}


def load_profiles(exemplars: list[LocalPdf], cache: Cache | None = None
                  ) -> list[tuple[LocalPdf, dict | None]]:
    """Every exemplar with its profile (None: structure not readable)."""
    out = []
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
        out.append((pdf, prof or None))
    return out


def aggregate(profiles: list[dict], venue: str) -> dict:
    """Benchmark dict (arxiv_cs_cl.json shape + venue_stats)."""
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


def build_venue_benchmark(exemplars: list[LocalPdf], venue: str,
                          cache: Cache | None = None) -> dict | None:
    """Benchmark dict from the target journal's papers, or None with
    fewer than MIN_EXEMPLARS readable ones."""
    profiles = [p for _, p in load_profiles(exemplars, cache) if p]
    if len(profiles) < MIN_EXEMPLARS:
        return None
    return aggregate(profiles, venue)


def manuscript_abstract(parsed: ParsedDocument) -> str | None:
    abstract_sec = next((s for s in parsed.sections if s.title.strip().rstrip(":：") == "摘要"), None)
    if abstract_sec is None:
        return None
    paras = [p.text for p in parsed.paragraphs if p.section_id == abstract_sec.id]
    return "".join(t for t in paras if not re.match(r"(关键词|分类号|DOI)", t.strip())) or None


def manuscript_stats(parsed: ParsedDocument, year: int | None = None) -> dict[str, float | None]:
    """The same journal-level indicators for the manuscript."""
    refs = [r for r in parsed.references if r.origin == "list"]
    years = [r.year for r in refs if r.year]
    text = "\n".join(p.text for p in parsed.paragraphs)
    abstract = manuscript_abstract(parsed)
    captions = "\n".join(p.text for p in parsed.paragraphs if p.caption) or text
    return {
        "n_refs": len(refs),
        "recent_share": _recent_share(years, year or date.today().year),
        "foreign_share": (sum(1 for r in refs if r.lang != "zh") / len(refs)) if refs else None,
        "abstract_chars": len(_CJK.findall(abstract)) if abstract is not None else None,
        "n_figures": len(set(re.findall(r"图\s*(\d+)", captions))),
        "n_tables": len(set(re.findall(r"表\s*(\d+)", captions))),
    }
