"""Word "接受/拒绝全部修订" 的模拟：用于导出自检与测试。

- reject_all(root): 去掉所有 w:ins，展开 w:del（w:delText 还原为 w:t），
  移除段落标记上的 ins/del 标记与批注元素——还原后的段落文本应与原文
  完全一致。
- accept_all(root): 去掉所有 w:del（含被删段落），展开 w:ins，移除标记。
"""

from __future__ import annotations

from copy import deepcopy

from lxml import etree

from ..parse import docx_xml as dx

W_DEL = dx.qn("del")
W_INS = dx.qn("ins")
W_DELTEXT = dx.qn("delText")
W_RPR = dx.qn("rPr")
W_PPR = dx.qn("pPr")
W_CRS = dx.qn("commentRangeStart")
W_CRE = dx.qn("commentRangeEnd")
W_CREF = dx.qn("commentReference")
_W_P = dx.W_P
_W_R = dx.W_R


def _strip_comments(root: etree._Element) -> None:
    for el in list(root.iter(W_CRS)) + list(root.iter(W_CRE)):
        el.getparent().remove(el)
    for r in list(root.iter(_W_R)):
        if r.find(W_CREF) is not None:
            r.getparent().remove(r)


def _para_mark_tag(p: etree._Element) -> str | None:
    """'ins' / 'del' if the paragraph mark carries that track-change tag."""
    ppr = p.find(W_PPR)
    if ppr is None:
        return None
    rpr = ppr.find(W_RPR)
    if rpr is None:
        return None
    for tag in (W_INS, W_DEL):
        if rpr.find(tag) is not None:
            return "ins" if tag == W_INS else "del"
    return None


def _unwrap(el: etree._Element) -> None:
    """Replace ``el`` by its children, in place."""
    parent = el.getparent()
    idx = list(parent).index(el)
    for child in list(el):
        el.remove(child)
        parent.insert(idx, child)
        idx += 1
    parent.remove(el)


def _unwrap_all(root: etree._Element, tag: str) -> None:
    for el in list(root.iter(tag)):
        _unwrap(el)


def _remove_all(root: etree._Element, tag: str) -> None:
    for el in list(root.iter(tag)):
        el.getparent().remove(el)


def _drop_mark(root: etree._Element, tag: str) -> None:
    """Remove ins/del elements living inside paragraph-mark rPr."""
    for ppr in root.iter(W_PPR):
        rpr = ppr.find(W_RPR)
        if rpr is None:
            continue
        for m in rpr.findall(tag):
            rpr.remove(m)


def simulate(root: etree._Element, mode: str) -> etree._Element:
    """Return a new w:document tree after accept-all or reject-all."""
    root = deepcopy(root)
    _strip_comments(root)
    body = root if root.tag == dx.W_BODY else root.find(dx.W_BODY)

    if mode == "reject":
        for p in list(body.iter(_W_P)):
            if _para_mark_tag(p) == "ins":
                p.getparent().remove(p)
        _remove_all(root, W_INS)
        # unwrap w:del; their runs' delText becomes visible text again
        for d in list(root.iter(W_DEL)):
            for t in d.iter(W_DELTEXT):
                t.tag = dx.W_T
        _unwrap_all(root, W_DEL)
        _drop_mark(root, W_DEL)
    elif mode == "accept":
        for p in list(body.iter(_W_P)):
            if _para_mark_tag(p) == "del":
                p.getparent().remove(p)
        _remove_all(root, W_DEL)
        _unwrap_all(root, W_INS)
        _drop_mark(root, W_INS)
    else:
        raise ValueError(mode)
    return root


def simulated_texts(root: etree._Element, mode: str) -> list[str]:
    """Paragraph texts (in document order) after accept/reject."""
    new_root = simulate(root, mode)
    return [dx.paragraph_text_map(p)[0] for _, p in dx.iter_paragraphs(new_root)]
