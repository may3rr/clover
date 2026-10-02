"""导出带批注与修订的 docx。

拷贝原 docx 的 zip，只改写必要部件；原文件永不修改。

顺序（避免偏移漂移）：
1. 按段落收集所有修订/批注锚点的边界偏移，一次性切分 run；
2. 在包装之前把每个锚点解析成具体的 run 元素列表；
3. 应用行内修订（w:del + w:ins）；
4. 应用参考文献移动（原段落整体 w:del + 段落标记删除；深拷贝改写标签
   后整体 w:ins + 段落标记插入；按目标顺序插到前驱当前元素之后）；
5. 应用批注（被移动条目上的批注落到插入的副本上）。

OOXML 顺序约束（破坏顺序 Word 会报文件损坏）：
- 段落标记 rPr（CT_ParaRPr）中 w:ins/w:del 必须最先出现；
- pPr 中 rPr 在其余子元素之后、sectPr 之前；
- w:id 从文档现有最大值 +1 开始；comment id 从现有批注最大值 +1 开始。
"""

from __future__ import annotations

import logging
import re
import tempfile
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from ..parse import docx_xml as dx
from ..parse.parser import parse_docx
from ..schema import Report
from .simulate import simulate, simulated_texts

log = logging.getLogger(__name__)

W = dx.qn
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
AUTHOR = "引用体检"
INITIALS = "体检"

_TEXT_TAGS = dx._TEXT_TAGS
W_T, W_R, W_P = dx.W_T, dx.W_R, dx.W_P
W_RPR, W_PPR = dx.W_RPR, dx.W_PPR
W_DEL, W_INS = dx.qn("del"), dx.qn("ins")
W_DELTEXT = dx.qn("delText")
W_ID, W_AUTHOR, W_DATE, W_INITIALS = (
    dx.qn("id"), dx.qn("author"), dx.qn("date"), dx.qn("initials"))
W_CRS, W_CRE, W_CREF = (
    dx.qn("commentRangeStart"), dx.qn("commentRangeEnd"),
    dx.qn("commentReference"))
W_SECTPR = dx.qn("sectPr")
_W_DASH = re.compile(r"\s*[-–—~～]\s*")


# ---------------------------------------------------------------- output


def _default_out(src: Path) -> Path:
    directory = src.parent
    tmp = Path(tempfile.gettempdir()).resolve()
    try:
        src.resolve().relative_to(tmp)
        directory = Path.home() / "Downloads"  # uploaded copy -> Downloads
    except ValueError:
        pass
    stem = src.stem
    for k in range(1, 1000):
        suffix = "（引用体检）" if k == 1 else f"（引用体检 {k}）"
        cand = directory / f"{stem}{suffix}.docx"
        if not cand.exists():
            return cand
    raise RuntimeError("无法生成输出文件名")


# ------------------------------------------------------------- splitting


def _run_text(run: etree._Element) -> str:
    return "".join(dx._render(c) for c in run if c.tag in _TEXT_TAGS)


def _split_run(run: etree._Element, offset: int) -> etree._Element:
    """Split ``run`` into two sibling runs at ``offset`` chars of text.
    Returns the new right-hand run (inserted after ``run``)."""
    assert 0 < offset < len(_run_text(run))
    new_run = etree.Element(W_R, nsmap=run.nsmap)
    rpr = run.find(W_RPR)
    if rpr is not None:
        new_run.append(deepcopy(rpr))
    pos = 0
    moving = False
    for child in list(run):
        if child.tag == W_RPR:
            continue
        if child.tag not in _TEXT_TAGS:
            if moving:
                run.remove(child)
                new_run.append(child)
            continue  # non-text children stay in the left run
        w = len(dx._render(child))
        if moving or pos >= offset:
            run.remove(child)
            new_run.append(child)
            moving = True
            continue
        if pos + w <= offset:
            pos += w
            continue
        # split inside this w:t (tab/br are atomic and never hit this)
        keep = offset - pos
        left_t, right_t = (child.text or "")[:keep], (child.text or "")[keep:]
        child.text = left_t
        child.set(XML_SPACE, "preserve")
        new_child = deepcopy(child)
        new_child.text = right_t
        new_child.set(XML_SPACE, "preserve")
        new_run.append(new_child)
        moving = True
        pos += w  # pos not used afterwards
    run.addnext(new_run)
    return new_run


def _split_paragraph(p: etree._Element, boundaries: set[int]) -> None:
    """Split runs at every boundary offset (one pass, rPr preserved)."""
    _, segs = dx.paragraph_text_map(p)
    groups: list[list] = []  # [run, start, end]
    for s in segs:
        if groups and groups[-1][0] is s.run:
            groups[-1][2] = s.end
        else:
            groups.append([s.run, s.start, s.end])
    for run, start, end in groups:
        if run is None:
            continue
        for cut in sorted(b for b in boundaries if start < b < end):
            run = _split_run(run, cut - start)
            start = cut


def _anchor_runs(
    p: etree._Element, start: int, end: int
) -> list[etree._Element]:
    """Run elements fully inside [start, end) of the paragraph text."""
    _, segs = dx.paragraph_text_map(p)
    runs: list[etree._Element] = []
    for s in segs:
        if s.run is not None and s.start >= start and s.end <= end:
            if not runs or runs[-1] is not s.run:
                runs.append(s.run)
    return runs


# ----------------------------------------------------------- track wraps


class _Ids:
    def __init__(self, root: etree._Element, comments_root: etree._Element | None):
        wid = 0
        for el in root.iter():
            v = el.get(W_ID)
            if v is not None and v.isdigit():
                wid = max(wid, int(v))
        self._wid = wid
        cid = 0
        if comments_root is not None:
            for c in comments_root.iter(dx.qn("comment")):
                v = c.get(W_ID)
                if v is not None and v.lstrip("-").isdigit():
                    cid = max(cid, int(v))
        for el in root.iter(W_CRS):
            v = el.get(W_ID)
            if v is not None and v.isdigit():
                cid = max(cid, int(v))
        self._cid = cid + 1

    def wid(self) -> str:
        self._wid += 1
        return str(self._wid)

    def cid(self) -> int:
        v = self._cid
        self._cid += 1
        return v


def _track(tag: str, ids: _Ids, date: str) -> etree._Element:
    el = etree.Element(dx.qn(tag))
    el.set(W_ID, ids.wid())
    el.set(W_AUTHOR, AUTHOR)
    el.set(W_DATE, date)
    return el


def _retag_del_text(wrapper: etree._Element) -> None:
    for t in wrapper.iter(W_T):
        t.tag = W_DELTEXT


def _wrap_runs(runs: list[etree._Element], tag: str, ids: _Ids,
               date: str) -> etree._Element:
    """Wrap a contiguous run list in one w:del/w:ins element."""
    first = runs[0]
    parent = first.getparent()
    wrap = _track(tag, ids, date)
    parent.insert(list(parent).index(first), wrap)
    for r in runs:
        wrap.append(r)  # moves r
    return wrap


def _apply_inline_revision(
    runs: list[etree._Element], new_text: str, ids: _Ids, date: str
) -> None:
    wrap = _wrap_runs(runs, "del", ids, date)
    _retag_del_text(wrap)
    ins = _track("ins", ids, date)
    ins_r = etree.SubElement(ins, W_R)
    rpr = runs[0].find(W_RPR)
    if rpr is not None:
        ins_r.append(deepcopy(rpr))
    t = etree.SubElement(ins_r, W_T)
    t.text = new_text
    t.set(XML_SPACE, "preserve")
    wrap.addnext(ins)


def _para_mark(p: etree._Element, tag: str, ids: _Ids, date: str) -> None:
    """Mark the paragraph mark as inserted/deleted (schema-safe order)."""
    ppr = p.find(W_PPR)
    if ppr is None:
        ppr = etree.Element(W_PPR)
        p.insert(0, ppr)
    rpr = ppr.find(W_RPR)
    if rpr is None:
        rpr = etree.Element(W_RPR)
        # rPr comes after the other pPr children, before sectPr/pPrChange
        sect = ppr.find(W_SECTPR)
        pprc = ppr.find(dx.qn("pPrChange"))
        idx = len(ppr)
        for i, ch in enumerate(ppr):
            if ch is sect or ch is pprc:
                idx = i
                break
        ppr.insert(idx, rpr)
    mark = _track(tag, ids, date)  # ins/del must come FIRST inside rPr
    rpr.insert(0, mark)


def _all_runs(p: etree._Element) -> list[etree._Element]:
    return [r for r in p.iter(W_R)]


def _wrap_para_runs(p: etree._Element, tag: str, ids: _Ids,
                    date: str) -> None:
    """Wrap every run of ``p`` in its own w:del/w:ins (deepest-first so
    nested containers keep working)."""
    for r in _all_runs(p):
        parent = r.getparent()
        wrap = _track(tag, ids, date)
        parent.insert(list(parent).index(r), wrap)
        wrap.append(r)
        if tag == "del":
            _retag_del_text(wrap)


def _replace_range(p: etree._Element, start: int, end: int,
                   new_text: str) -> None:
    """Replace paragraph text [start, end) with new_text in place."""
    text, segs = dx.paragraph_text_map(p)
    covering = [s for s in segs if s.end > start and s.start < end]
    if not covering:
        return
    first, last = covering[0], covering[-1]
    if first.node is last.node:
        n = first.node
        n.text = (n.text or "")[: start - first.start] + new_text + \
            (n.text or "")[end - first.start:]
        n.set(XML_SPACE, "preserve")
        return
    first.node.text = (first.node.text or "")[: start - first.start] + new_text
    first.node.set(XML_SPACE, "preserve")
    last.node.text = (last.node.text or "")[end - last.start:]
    last.node.set(XML_SPACE, "preserve")
    for s in covering[1:-1]:
        s.node.getparent().remove(s.node)


def _diff_span(old: str, new: str) -> tuple[int, int, str]:
    """Common prefix/suffix diff: returns (start, end, replacement)."""
    i = 0
    while i < len(old) and i < len(new) and old[i] == new[i]:
        i += 1
    j = 0
    while j < len(old) - i and j < len(new) - i and \
            old[len(old) - 1 - j] == new[len(new) - 1 - j]:
        j += 1
    return i, len(old) - j, new[i: len(new) - j]


# ------------------------------------------------------------- comments


def _comment_el(cid: int, title: str, detail: str, date: str) -> etree._Element:
    c = etree.Element(dx.qn("comment"))
    c.set(W_ID, str(cid))
    c.set(W_AUTHOR, AUTHOR)
    c.set(W_INITIALS, INITIALS)
    c.set(W_DATE, date)
    for line in [title] + [ln for ln in detail.splitlines() if ln.strip()]:
        p = etree.SubElement(c, W_P)
        r = etree.SubElement(p, W_R)
        t = etree.SubElement(r, W_T)
        t.text = line
        t.set(XML_SPACE, "preserve")
    return c


def _lift_to_change_wrapper(el: etree._Element) -> etree._Element:
    """If the element was wrapped by our w:del/w:ins, the comment range
    should wrap the wrapper instead."""
    parent = el.getparent()
    while parent is not None and parent.tag in (W_DEL, W_INS):
        el = parent
        parent = el.getparent()
    return el


def _place_comment(p: etree._Element, runs: list[etree._Element],
                   cid: int, ids: _Ids, date: str,
                   comment_ref_style: bool) -> None:
    crs = etree.Element(W_CRS)
    crs.set(W_ID, str(cid))
    cre = etree.Element(W_CRE)
    cre.set(W_ID, str(cid))
    ref_run = etree.Element(W_R)
    if comment_ref_style:
        rpr = etree.SubElement(ref_run, W_RPR)
        etree.SubElement(rpr, dx.qn("rStyle")).set(dx.W_VAL, "CommentReference")
    cref = etree.SubElement(ref_run, W_CREF)
    cref.set(W_ID, str(cid))

    if not runs:
        # empty paragraph: range covers nothing, markers hug the pPr
        ppr = p.find(W_PPR)
        idx = list(p).index(ppr) + 1 if ppr is not None else 0
        p.insert(idx, crs)
        p.insert(idx + 1, cre)
        p.insert(idx + 2, ref_run)
        return
    first = _lift_to_change_wrapper(runs[0])
    last = _lift_to_change_wrapper(runs[-1])
    # when the anchor was rewritten, cover the ins that follows the del
    nxt = last.getnext()
    if last.tag == W_DEL and nxt is not None and nxt.tag == W_INS:
        last = nxt
    parent = first.getparent()
    parent.insert(list(parent).index(first), crs)
    lparent = last.getparent()
    idx = list(lparent).index(last) + 1
    lparent.insert(idx, cre)
    lparent.insert(idx + 1, ref_run)


# ------------------------------------------------------------ assembly


_CONTENT_TYPE_COMMENTS = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml."
    "comments+xml")
_REL_COMMENTS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    "/comments")
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_COMMENTS_SKELETON = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:comments xmlns:w="{dx.W_NS}"/>'
)


def _has_comment_ref_style(styles_root: etree._Element | None) -> bool:
    if styles_root is None:
        return False
    for st in styles_root.iter(dx.qn("style")):
        if st.get(dx.qn("styleId")) == "CommentReference":
            return True
        name = st.find(dx.qn("name"))
        if name is not None and name.get(dx.W_VAL) in {
                "comment reference", "annotation reference"}:
            return True
    return False


def export_report(
    src_path: str | Path, report: Report, out_path: str | Path | None = None
) -> Path:
    src = Path(src_path)
    out = Path(out_path) if out_path else _default_out(src)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with zipfile.ZipFile(src) as zf:
        names = zf.namelist()
        blobs = {n: zf.read(n) for n in names}

    doc_root = etree.fromstring(blobs["word/document.xml"])
    styles_root = (
        etree.fromstring(blobs["word/styles.xml"])
        if "word/styles.xml" in blobs else None
    )
    comments_root = (
        etree.fromstring(blobs["word/comments.xml"])
        if "word/comments.xml" in blobs else
        etree.fromstring(_COMMENTS_SKELETON.encode())
    )
    comment_ref_style = _has_comment_ref_style(styles_root)

    p_by_id = {pid: p for pid, p in dx.iter_paragraphs(doc_root)}
    para_len = {p.id: len(p.text) for p in report.paragraphs}

    # ---- resolve finding anchors ---------------------------------------
    # anchor None -> first section heading, else first non-empty paragraph
    def _finding_target(f) -> tuple[str, int, int]:
        if f.anchor is not None:
            pid = f.anchor.paragraph_id
            s, e = f.anchor.start, f.anchor.end
            if e <= s:
                s, e = 0, para_len.get(pid, 0)
            return pid, s, e
        for sec in report.sections:
            if sec.heading_paragraph_id:
                return sec.heading_paragraph_id, 0, para_len.get(
                    sec.heading_paragraph_id, 0)
        for par in report.paragraphs:
            if par.text.strip():
                return par.id, 0, len(par.text)
        return report.paragraphs[0].id if report.paragraphs else "p0", 0, 0

    moves = [r for r in report.revisions
             if r.kind == "ref_reorder" and r.move_after is not None]
    inline = [r for r in report.revisions
              if not (r.kind == "ref_reorder" and r.move_after is not None)]

    # ---- step 1: split runs at every anchor boundary --------------------
    boundaries: dict[str, set[int]] = {}
    for r in inline:
        boundaries.setdefault(r.anchor.paragraph_id, set()).update(
            {r.anchor.start, r.anchor.end})
    for f in report.findings:
        pid, s, e = _finding_target(f)
        boundaries.setdefault(pid, set()).update({s, e})
    for pid, bs in boundaries.items():
        p = p_by_id.get(pid)
        if p is not None:
            _split_paragraph(p, bs)

    # ---- step 2: resolve anchors to run lists (before any wrapping) -----
    resolved_inline: list[tuple[list[etree._Element], object]] = []
    applied_spans: dict[str, list[tuple[int, int]]] = {}
    for r in inline:
        p = p_by_id.get(r.anchor.paragraph_id)
        if p is None:
            continue
        span = (r.anchor.start, r.anchor.end)
        if any(not (span[1] <= a or span[0] >= b)
               for a, b in applied_spans.setdefault(r.anchor.paragraph_id, [])):
            log.warning("overlapping revision dropped: %s @%s", r.kind,
                        r.anchor.paragraph_id)
            continue
        applied_spans[r.anchor.paragraph_id].append(span)
        runs = _anchor_runs(p, r.anchor.start, r.anchor.end)
        resolved_inline.append((runs, r, p))

    resolved_findings: list[tuple[str, int, int, list[etree._Element]]] = []
    for f in report.findings:
        pid, s, e = _finding_target(f)
        runs = _anchor_runs(p_by_id[pid], s, e) if pid in p_by_id else []
        resolved_findings.append((pid, s, e, runs))

    ids = _Ids(doc_root, comments_root)

    # ---- step 3: inline revisions ----------------------------------------
    for runs, r, p in resolved_inline:
        if not runs and r.anchor.start < r.anchor.end:
            continue
        if not runs:
            # pure insertion at a point: insert an ins after the run whose
            # text ends at the anchor offset
            _, segs = dx.paragraph_text_map(p)
            prev = [s for s in segs if s.end <= r.anchor.start]
            if not prev:
                continue
            ins = _track("ins", ids, date)
            ins_r = etree.SubElement(ins, W_R)
            t = etree.SubElement(ins_r, W_T)
            t.text = r.new
            t.set(XML_SPACE, "preserve")
            prev[-1].run.addnext(ins)
            continue
        _apply_inline_revision(runs, r.new, ids, date)

    # ---- step 4: paragraph moves -----------------------------------------
    current_elem: dict[str, etree._Element] = {}   # pid -> current element
    copy_of: dict[str, etree._Element] = {}
    first_ref_pid = next(
        (r.paragraph_id for r in report.references if r.paragraph_id), None)
    for rev in moves:
        pid = rev.anchor.paragraph_id
        orig = p_by_id.get(pid)
        if orig is None:
            continue
        copy_p = deepcopy(orig)
        a, b, repl = _diff_span(rev.old, rev.new)
        if repl or a < b:
            _replace_range(copy_p, a, b, repl)
        # original: delete all runs + paragraph mark
        _wrap_para_runs(orig, "del", ids, date)
        _para_mark(orig, "del", ids, date)
        # copy: insert all runs + paragraph mark
        _wrap_para_runs(copy_p, "ins", ids, date)
        _para_mark(copy_p, "ins", ids, date)
        if rev.move_after == "__start__":
            anchor_pid = first_ref_pid
            ref_p = p_by_id.get(anchor_pid) if anchor_pid else None
            if ref_p is not None:
                ref_p.addprevious(copy_p)
            else:
                orig.addnext(copy_p)
        else:
            pred = current_elem.get(rev.move_after)
            if pred is None:
                pred = p_by_id.get(rev.move_after)
            if pred is not None:
                pred.addnext(copy_p)
            else:
                orig.addnext(copy_p)
        current_elem[pid] = copy_p
        copy_of[pid] = copy_p

    # ---- step 5: comments --------------------------------------------------
    has_comments = "word/comments.xml" in blobs
    new_comments_root = comments_root
    for f, (pid, s, e, runs) in zip(report.findings, resolved_findings):
        cid = ids.cid()
        target_runs = runs
        target_p = p_by_id.get(pid)
        if pid in copy_of:
            target_p = copy_of[pid]
            target_runs = _anchor_runs(target_p, s, e)
        if target_p is None:
            continue
        _place_comment(target_p, target_runs, cid, ids, date,
                       comment_ref_style)
        new_comments_root.append(
            _comment_el(cid, f.title, f.detail, date))

    # ---- write the new zip --------------------------------------------------
    blobs["word/document.xml"] = etree.tostring(
        doc_root, xml_declaration=True, encoding="UTF-8",
        standalone=True)
    want_comments = has_comments or bool(report.findings)
    if want_comments:
        blobs["word/comments.xml"] = etree.tostring(
            new_comments_root, xml_declaration=True, encoding="UTF-8",
            standalone=True)
    if not has_comments and report.findings:
        ct = etree.fromstring(blobs["[Content_Types].xml"])
        part = "/word/comments.xml"
        if not any(o.get("PartName") == part for o in ct.iter(
                f"{{{_CT_NS}}}Override")):
            o = etree.SubElement(ct, f"{{{_CT_NS}}}Override")
            o.set("PartName", part)
            o.set("ContentType", _CONTENT_TYPE_COMMENTS)
        blobs["[Content_Types].xml"] = etree.tostring(
            ct, xml_declaration=True, encoding="UTF-8", standalone=True)
        rels_name = "word/_rels/document.xml.rels"
        rels = etree.fromstring(blobs[rels_name])
        taken = {r.get("Id") for r in rels.iter(f"{{{_REL_NS}}}Relationship")}
        i = 1
        while f"rId{i}" in taken:
            i += 1
        rel = etree.SubElement(rels, f"{{{_REL_NS}}}Relationship")
        rel.set("Id", f"rId{i}")
        rel.set("Type", _REL_COMMENTS)
        rel.set("Target", "comments.xml")
        blobs[rels_name] = etree.tostring(
            rels, xml_declaration=True, encoding="UTF-8", standalone=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in names:
            zf.writestr(n, blobs[n])
        if "word/comments.xml" not in names and want_comments:
            zf.writestr("word/comments.xml", blobs["word/comments.xml"])

    _self_check(src, doc_root, out, report)
    log.info("exported %s", out)
    return out


# ------------------------------------------------------------- self-check


def _strip_label(raw: str) -> str:
    return re.sub(r"^\s*[\[\(（【［]?\d{1,3}[\]\)）】］]?\s*[\.、]?\s*", "",
                  raw).strip()


def _self_check(src: Path, out_root: etree._Element, out: Path,
                report: Report) -> None:
    # (a) the exported file still parses
    acc_parsed = parse_docx(out)

    src_root = etree.fromstring(zipfile.ZipFile(src).read("word/document.xml"))

    # (b) reject-all reproduces the original texts exactly. If the source
    # itself already carries tracked changes, "original" is its own
    # fully-rejected text.
    orig = simulated_texts(src_root, "reject")
    rejected = simulated_texts(out_root, "reject")
    if rejected != orig:
        raise RuntimeError(
            "自检失败：拒绝全部修订后文本与原文不一致")

    # (c) accept-all: for numeric reorders the ref order equals
    # first-appearance order and every marker resolves to the same works
    if not any(r.kind == "ref_reorder" and r.move_after
               for r in report.revisions):
        return
    acc_root = simulate(out_root, "accept")
    tmp = Path(tempfile.mkdtemp()) / "accept.docx"
    with zipfile.ZipFile(src) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "word/document.xml":
                data = etree.tostring(
                    acc_root, xml_declaration=True, encoding="UTF-8",
                    standalone=True)
            zout.writestr(n, data)
    acc = parse_docx(tmp)
    orig_text = {r.id: _strip_label(r.raw) for r in report.references}
    acc_text = {r.id: _strip_label(r.raw) for r in acc.references}
    first_seen: list[str] = []
    for m in report.markers:
        for rid in m.ref_ids:
            if rid not in first_seen:
                first_seen.append(rid)
    first_seen += [r.id for r in report.references if r.id not in first_seen]
    expected = [orig_text[i] for i in first_seen]
    actual = [acc_text[r.id] for r in acc.references]
    if actual != expected:
        raise RuntimeError(
            f"自检失败：接受全部修订后参考文献顺序错误 {actual} != {expected}")
    for mo, ma in zip(report.markers, acc.markers):
        if {orig_text[i] for i in mo.ref_ids if i in orig_text} != \
                {acc_text[i] for i in ma.ref_ids if i in acc_text}:
            raise RuntimeError(
                "自检失败：接受全部修订后标记解析结果与原文不一致")
