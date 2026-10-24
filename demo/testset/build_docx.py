"""F8: convert the five pre-2021 manuscripts into clean docx for the eval corpus.

CNKI journal PDFs render citation markers as bare superscript digits glued to
words ("知识1."), so plain text extraction loses the [n] markers. This
converter reassembles span-level text (pymupdf dict mode), wraps superscript
digit runs as [n], drops masthead/header/footer/funding/bio noise, NFKC
normalises, rebuilds paragraphs with an adaptive line-gap heuristic, splits
the reference list into one paragraph per entry, and writes a docx the parse
layer handles natively (Word styles + plain [n] markers).

Usage:
    python demo/testset/build_docx.py
Outputs: zh_papers/<dir>/manuscript.docx (+ zh_html/jos_mrc_body.json input)
"""

from __future__ import annotations

import json
import re
import statistics
import unicodedata
from pathlib import Path

import fitz
from docx import Document

HERE = Path(__file__).resolve().parent

# journal mastheads / running heads / page furniture — dropped unconditionally
MASTHEAD = re.compile(
    r"(计算机研究与发展|电子学报|计\s*算\s*机\s*学\s*报|自\s*动\s*化\s*学\s*报|"
    r"Journal\s+of\s+Computer|ACTA\s+ELECTRONICA|ACTA\s*AUTOMATICA|"
    r"CHINESE\s+JOURNAL|J\s*o\s*u\s*r)"
)
NOISE = re.compile(
    r"^(第\s*\d+\s*卷|第\s*\d+\s*期|Vol\.|No\.|20\d\d\s*年|\d{4}年\d+月|\d+\s*$|"
    r"收稿日期|修回日期|基金项目|本课题|国家高技术研究|ＤＯＩ|DOI[:：]|CNKI[:：]|"
    r"网络首发|引用格式|中图法分类号|文章编号|http|www\.|HTML|万方数据|"
    r"随机访问|Copyright|©|（责任编辑|本文责任编辑|责編|责任编辑)"
)
BIO = re.compile(
    r"(教授|副教授|博士研究生|硕士研究生|讲师|研究员).{0,40}(研究方向|主要研究)"
    r"|E-?mail|出生年|生于|获得.{0,8}博士学位|本课题得到|责任编委|审稿人|作者简介|"
    r"born\s+in\s+\d{4}|research\s+interests?\s+include|Member\s+of\s+China"
)
HEAD = re.compile(r"^(\d{1,2}(\.\d{1,2})*)\s+([^\d\s.].{0,40})$")
REF_HEAD = re.compile(r"^参\s*考\s*文\s*献")
TERMINAL = tuple("。！？；：\"）】]")


def nk(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def is_marker_span(text: str, size: float, body_size: float, flags: int) -> bool:
    ts = nk(text).strip()
    if not ts or not re.fullmatch(r"\d{1,3}", ts):
        return False
    return (flags & 1) or size < body_size - 0.9


def page_lines(page: fitz.Page, ref_bound: int = 400, wrap: bool = True):
    """Lines as (x0, y0, wrapped_text, raw_text); superscript digit runs
    become [n] in wrapped_text. ref_bound caps the marker value so years
    (2013) and table indices never become markers."""
    sizes: dict[float, int] = {}
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = nk(s["text"]).strip()
                if len(t) >= 4 and re.search(r"[\u4e00-\u9fff]", t):
                    k = round(s["size"], 1)
                    sizes[k] = sizes.get(k, 0) + len(t)
    body_size = max(sizes, key=sizes.get) if sizes else 9.0

    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            raw, pieces = "", []
            for si, s in enumerate(l["spans"]):
                raw += nk(s["text"])
                t = nk(s["text"])
                ts = t.strip()
                val_ok = False
                if ts and re.fullmatch(r"\d{1,3}([,，]\d{1,3}|[-－]\d{1,3})?", ts):
                    head = int(re.split(r"[,，\-－]", ts)[0])
                    val_ok = head <= ref_bound
                prev_cjk = bool(re.search(r"[\u4e00-\u9fff））”」\"、，。；：]\s*$",
                                          "".join(pieces)))
                small = s["size"] < body_size - 0.9
                marker = (wrap and val_ok and s["size"] > 4.5 and small
                          and ((s["flags"] & 1) or prev_cjk))
                if marker:
                    pieces.append("[" + ts.replace("，", ",").replace("－", "-") + "]")
                else:
                    pieces.append(t)
            wrapped = "".join(pieces).strip()
            if wrapped:
                starts_small = bool(l["spans"]) and is_marker_span(
                nk(l["spans"][0]["text"]).strip(), l["spans"][0]["size"],
                body_size, l["spans"][0]["flags"])
            out.append((round(l["bbox"][0]), round(l["bbox"][1]), wrapped,
                        raw.strip(), starts_small))
    return out


def line_filter(lines, H):
    keep = []
    for x, y, wrapped, raw, starts_small in lines:
        if y < 46 or y > H - 32:
            continue
        if MASTHEAD.search(raw):
            continue
        if NOISE.search(raw) and len(raw) < 70:
            continue
        if BIO.search(raw):
            continue
        keep.append((x, y, wrapped, starts_small))
    return keep


def assemble(lines, width, two_column: bool):
    """Lines -> paragraph strings with an adaptive line-gap split."""
    if two_column:
        mid = width / 2 - 12
        cols = [sorted([l for l in lines if l[0] < mid], key=lambda l: l[1]),
                sorted([l for l in lines if l[0] >= mid], key=lambda l: l[1])]
    else:
        cols = [sorted(lines, key=lambda l: l[1])]

    paras = []
    for col in cols:
        gaps = [b[1] - a[1] for a, b in zip(col, col[1:]) if b[1] - a[1] < 30]
        med = statistics.median(gaps) if gaps else 10.0
        thr = max(med * 1.5, med + 3.0)
        buf, last_y = "", None
        for x, y, wrapped, starts_small in col:
            force = re.match(r"^(\[\d{1,3}\]\s*\S|\d{1,2}(\.\d{1,2})*\s+[^\d\s]|"
                             r"摘\s*要|关键词|参\s*考\s*文\s*献|Abstract|Keywords)", wrapped)
            if buf and ((last_y is not None and y - last_y > thr) or force):
                paras.append(buf)
                buf = ""
            piece = wrapped
            if buf and starts_small and re.match(r"^\d{1,3}", wrapped) \
                    and re.search(r"[\u4e00-\u9fff））”]$", buf):
                piece = "[" + piece + "]"
            buf += piece
            last_y = y
        if buf:
            paras.append(buf)
    return [re.sub(r"\s+", " ", p).strip() for p in paras if p.strip()]


def merge_wrapped(paras):
    """Glue paragraphs that are continuations of the previous sentence."""
    out: list[str] = []
    for p in paras:
        if out and not re.match(r"^(\[\d{1,3}\]\s?\S|\d{1,2}(\.\d{1,2})*\s+[^\d\s]|"
                                r"摘\s*要|关键词|参考文献|Abstract|Keywords|作者简介|"
                                r"[A-ZＡ-Ｚ][a-zａ-ｚ]+\s+[A-ZＡ-Ｚ])", p) \
                and out[-1] and not out[-1].endswith(TERMINAL) \
                and not out[-1].endswith(("《", "（")):
            out[-1] += p
        else:
            out.append(p)
    return out


def extract_pages(pdf: Path, ref_bound: int, wrap: bool):
    """Per page: list of paragraph strings (two-column aware)."""
    doc = fitz.open(pdf)
    pages = []
    for pno in range(len(doc)):
        page = doc[pno]
        lines = line_filter(page_lines(page, ref_bound, wrap), page.rect.height)
        pages.append(assemble(lines, page.rect.width, True))
    return pages


def find_ref_start(pages):
    """(page_idx, para_idx) of the LAST standalone 参考文献 heading."""
    best = None
    for pi, paras in enumerate(pages):
        for qi, p in enumerate(paras):
            if p.strip() == "参考文献" or p.strip().startswith("参 考 文 献"):
                best = (pi, qi)
    return best


def extract_pdf_paragraphs(pdf: Path, two_column=True, ref_bound: int = 400):
    """Two passes: pass A (wrap on) locates the refs heading; pass B
    re-extracts from the ref page with wrapping off so volume/page digits in
    reference entries stay clean. Returns (body_paras, ref_paras).
    ref_paras carry no marker wrapping; entry numbers rely on literal [n] or
    the assembler's numbered-heading split."""
    pages_a = extract_pages(pdf, ref_bound, wrap=True)
    loc = find_ref_start(pages_a)
    if loc is None:
        return [p for pp in pages_a for p in pp], []
    pi, qi = loc
    body = [p for pp in pages_a[:pi] for p in pp] + pages_a[pi][:qi]
    pages_b = extract_pages(pdf, ref_bound, wrap=False)
    refs = pages_b[pi][qi:] if qi < len(pages_b[pi]) else []
    for pp in pages_b[pi + 1:]:
        refs.extend(pp)
    return body, refs


def split_refs(ref_paras):
    """Concatenate wrapped ref lines into [n]-prefixed entries; skip bios."""
    entries: list[str] = []
    for p in ref_paras:
        if not p:
            continue
        if BIO.search(p) or MASTHEAD.search(p):
            continue
        if re.match(r"^\[\d{1,3}\]", p):
            entries.append(p)
        elif re.match(r"^\d{1,3}\s+[A-ZＡ-Ｚ]", p) and len(p) > 20:
            entries.append(re.sub(r"^(\d{1,3})\s+", r"[\1] ", p))
        elif entries and not re.match(r"^(作者简介|参考文献)", p):
            entries[-1] += p
    return entries


def build_docx(body, ref_entries, out: Path, title: str):
    doc = Document()
    doc.add_paragraph(title, style="Title")
    for p in body:
        if p == title:
            continue
        if HEAD.match(p) and len(p) < 44:
            doc.add_paragraph(p, style="Heading 1")
        elif re.match(r"^摘\s*要", p):
            doc.add_paragraph(p, style="Heading 1")
        else:
            doc.add_paragraph(p)
    doc.add_paragraph("References", style="Heading 1")
    for e in ref_entries:
        doc.add_paragraph(e)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    markers = sum(len(re.findall(r"\[\d{1,3}\]", p)) for p in body)
    print(f"{out.parent.name}: body_paras={len(body)} markers={markers} refs={len(ref_entries)}")


JOBS = [
    # (pdf, out, title, body_pages_end(0-based, exclusive), ref_bound, refs_source)
    ("zh_papers/liuqiao_kg/manuscript.pdf", "zh_papers/liuqiao_kg/manuscript.docx",
     "知识图谱构建技术综述", 15, 70, ("pdf_pages", 14)),
    ("zh_papers/luohuilan_odt/manuscript.pdf", "zh_papers/luohuilan_odt/manuscript.docx",
     "基于深度学习的目标检测研究综述", 7, 90, ("pdf_pages", 6)),
    ("zh_papers/zhaoyangyang_tod/manuscript.pdf", "zh_papers/zhaoyangyang_tod/manuscript.docx",
     "任务型对话系统研究综述", 25, 220, ("pdf_pages", 24)),
    ("zh_pdfs/aas_yinhongpeng_2016.pdf", "zh_papers/yinhongpeng_odt/manuscript.docx",
     "基于视觉的目标检测与跟踪综述", 16, 232, ("json", "aas_yinhongpeng_odt.json")),
]

if __name__ == "__main__":
    for src, out, title, body_end, ref_bound, refs_src in JOBS:
        pdf = HERE / src
        if not pdf.exists():
            print(f"skip (missing): {src}")
            continue
        doc = fitz.open(pdf)
        sp = refs_src[1] if refs_src[0] == "pdf_pages" else None
        body: list[str] = []
        for pno in range(min(body_end, len(doc))):
            lines = line_filter(page_lines(doc[pno], ref_bound, True),
                                doc[pno].rect.height)
            pp = assemble(lines, doc[pno].rect.width, True)
            if sp is not None and pno == sp:
                idx = next((i for i, q in enumerate(pp) if "参考文献" in q), None)
                if idx is not None:
                    pp = pp[:idx]
            body.extend(pp)
        body = merge_wrapped(body)

        if refs_src[0] == "json":
            d = json.loads((HERE / "zh_refs" / refs_src[1]).read_text())
            entries = [f"[{r['n']}] {r['text']}" for r in d["refs"]]
        else:
            ref_paras: list[str] = []
            for pno in range(sp, len(doc)):
                lines = line_filter(page_lines(doc[pno], ref_bound, False),
                                    doc[pno].rect.height)
                pp = assemble(lines, doc[pno].rect.width, True)
                if pno == sp:
                    idx = next((i for i, q in enumerate(pp) if "参考文献" in q), None)
                    if idx is not None:
                        first = pp[idx].replace("参考文献", "", 1).strip()
                        pp = ([first] if first else []) + pp[idx + 1:]
                ref_paras.extend(pp)
            entries = split_refs(ref_paras)

        build_docx(body, entries, HERE / out, title)

    js = HERE / "zh_html/jos_mrc_body.json"
    if js.exists():
        data = json.loads(js.read_text())
        rj = json.loads((HERE / "zh_refs/jos_mrc_6048.json").read_text())
        entries = [f"[{i}] {t}" for i, t in enumerate(rj["refs"], 1)]
        build_docx(data["paragraphs"], entries,
                   HERE / "zh_papers/guyingjie_mrc/manuscript.docx",
                   data.get("title", "基于神经网络的机器阅读理解综述"))
    else:
        print("skip (no jos html yet): guyingjie_mrc")
