"""Marker detection unit tests (inline paragraph XML)."""

import json

from lxml import etree

from citecheck.parse import docx_xml as dx
from citecheck.parse.markers import detect_markers

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def detect(inner: str):
    p = etree.fromstring(f'<w:p {W}>{inner}</w:p>')
    text, segs = dx.paragraph_text_map(p)
    markers, managed = detect_markers(p, text, segs)
    return text, markers, managed


def run(inner: str, rpr: str = "") -> str:
    return f"<w:r>{rpr}{inner}</w:r>"


def test_numeric_variants():
    text, ms, _ = detect(
        run("<w:t>see </w:t>")
        + run("<w:t>[1]</w:t>")
        + run("<w:t> and </w:t>")
        + run("<w:t>[1,3]</w:t>")
        + run("<w:t> or </w:t>")
        + run("<w:t>[2-5]</w:t>")
        + run("<w:t> and </w:t>")
        + run("<w:t>[2–5]</w:t>")
        + run("<w:t>.</w:t>")
    )
    raws = [m.raw for m in ms]
    assert raws == ["[1]", "[1,3]", "[2-5]", "[2–5]"]
    for m in ms:
        assert m.kind == "numeric"
        assert text[m.start : m.end] == m.raw


def test_full_width_numeric():
    _, ms, _ = detect(run("<w:t>已有研究［3］表明</w:t>"))
    assert len(ms) == 1 and ms[0].raw == "［3］" and ms[0].kind == "numeric"


def test_author_year_paren():
    text, ms, _ = detect(
        run("<w:t>Prior work (Smith, 2020) and (Smith et al., 2020; Lee, 2021) "
            "plus (Smith &amp; Lee, 2020a) and （张三，2020）.</w:t>")
    )
    raws = [m.raw for m in ms]
    assert "(Smith, 2020)" in raws
    assert "(Smith et al., 2020; Lee, 2021)" in raws
    assert "(Smith & Lee, 2020a)" in raws
    assert "（张三，2020）" in raws
    for m in ms:
        assert m.kind == "author_year"
        assert text[m.start : m.end] == m.raw


def test_narrative_author_year():
    _, ms, _ = detect(
        run("<w:t>Smith et al. (2020) showed that 张三等(2020) and "
            "张三和李四（2020）agree.</w:t>")
    )
    raws = [m.raw for m in ms]
    assert "Smith et al. (2020)" in raws
    assert "张三等(2020)" in raws
    assert "张三和李四（2020）" in raws


def test_superscript_cluster():
    text, ms, _ = detect(
        run("<w:t>as shown</w:t>")
        + run("<w:t>2</w:t>", '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>')
        + run("<w:t>–5</w:t>", '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>')
        + run("<w:t> today</w:t>")
    )
    assert len(ms) == 1
    assert ms[0].kind == "superscript"
    assert ms[0].raw == "2–5"
    assert text[ms[0].start : ms[0].end] == "2–5"


def test_zotero_field_marker():
    payload = {
        "citationID": "x",
        "citationItems": [
            {"itemData": {"title": "Attention is all you need",
                          "issued": {"date-parts": [[2017]]}}}
        ],
    }
    inner = (
        run("<w:t>result </w:t>")
        + run('<w:fldChar w:fldCharType="begin"/>')
        + run("<w:instrText xml:space='preserve'> ZOTERO_ITEM CSL_CITATION "
              + json.dumps(payload, ensure_ascii=False) + " </w:instrText>")
        + run('<w:fldChar w:fldCharType="separate"/>')
        + run("<w:t>[1]</w:t>")
        + run('<w:fldChar w:fldCharType="end"/>')
        + run("<w:t> end</w:t>")
    )
    text, ms, managed = detect(inner)
    assert managed == "zotero"
    assert len(ms) == 1
    assert ms[0].kind == "zotero"
    assert ms[0].raw == "[1]"
    assert ms[0].items[0]["title"] == "Attention is all you need"


def test_field_result_not_double_detected():
    payload = {"citationItems": [{"itemData": {"title": "T"}}]}
    inner = (
        run('<w:fldChar w:fldCharType="begin"/>')
        + run("<w:instrText> ZOTERO_ITEM CSL_CITATION "
              + json.dumps(payload) + " </w:instrText>")
        + run('<w:fldChar w:fldCharType="separate"/>')
        + run("<w:t>[3]</w:t>")
        + run('<w:fldChar w:fldCharType="end"/>')
    )
    _, ms, _ = detect(inner)
    assert len(ms) == 1 and ms[0].kind == "zotero"


def test_no_markers():
    _, ms, managed = detect(run("<w:t>plain prose without citations.</w:t>"))
    assert ms == [] and managed is None
