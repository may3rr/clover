"""Unit tests for the text/offset rules in citecheck.parse.docx_xml.

Paragraph XML is built inline; fixture-level tests live in test_parse.py.
"""

from lxml import etree

from citecheck.parse import docx_xml as dx

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def para(inner: str) -> etree._Element:
    return etree.fromstring(f'<w:p {W}>{inner}</w:p>')


def run(inner: str, rpr: str = "") -> str:
    return f"<w:r>{rpr}{inner}</w:r>"


def test_plain_text_and_offsets():
    p = para(run("<w:t>Hello </w:t>") + run("<w:t>world</w:t>"))
    text, segs = dx.paragraph_text_map(p)
    assert text == "Hello world"
    assert len(segs) == 2
    assert segs[0].start == 0 and segs[0].text == "Hello "
    assert segs[1].start == 6 and segs[1].end == 11
    assert segs[1].run is not None


def test_tab_and_break():
    p = para(run("<w:t>a</w:t><w:tab/><w:t>b</w:t><w:br/><w:t>c</w:t>"))
    text, segs = dx.paragraph_text_map(p)
    assert text == "a\tb\nc"
    assert text[segs[1].start] == "\t"


def test_deleted_and_inserted_text():
    p = para(
        run("<w:t>keep </w:t>")
        + '<w:ins>' + run("<w:t>ins</w:t>") + "</w:ins>"
        + '<w:del>' + run("<w:delText>gone</w:delText>") + "</w:del>"
        + '<w:moveFrom>' + run("<w:t>moved</w:t>") + "</w:moveFrom>"
    )
    text, _ = dx.paragraph_text_map(p)
    assert text == "keep ins"


def test_complex_field_result_included_instr_excluded():
    p = para(
        run("<w:t>shown </w:t>")
        + run('<w:fldChar w:fldCharType="begin"/>')
        + run('<w:instrText xml:space="preserve"> ZOTERO_ITEM CSL_CITATION {} </w:instrText>')
        + run('<w:fldChar w:fldCharType="separate"/>')
        + run("<w:t>[1]</w:t>")
        + run('<w:fldChar w:fldCharType="end"/>')
        + run("<w:t> tail</w:t>")
    )
    text, segs = dx.paragraph_text_map(p)
    assert text == "shown [1] tail"
    fields = dx.paragraph_fields(p)
    assert len(fields) == 1
    f = fields[0]
    assert "ZOTERO_ITEM CSL_CITATION" in f.instr
    assert f.span == (6, 9)
    assert text[f.span[0] : f.span[1]] == "[1]"


def test_field_spanning_runs_and_endnote():
    p = para(
        run('<w:fldChar w:fldCharType="begin"/>')
        + run('<w:instrText> ADDIN EN.CITE </w:instrText>')
        + run('<w:instrText> &lt;data&gt; </w:instrText>')
        + run('<w:fldChar w:fldCharType="separate"/>')
        + run("<w:t>(Smi</w:t>")
        + run("<w:t>th, 2020)</w:t>")
        + run('<w:fldChar w:fldCharType="end"/>')
    )
    fields = dx.paragraph_fields(p)
    assert len(fields) == 1
    assert fields[0].instr.startswith("ADDIN EN.CITE")
    assert fields[0].span == (0, 13)


def test_fldsimple():
    p = para(
        '<w:fldSimple w:instr=" ZOTERO_ITEM CSL_CITATION {json} ">'
        + run("<w:t>(1)</w:t>")
        + "</w:fldSimple>"
        + run("<w:t> x</w:t>")
    )
    text, segs = dx.paragraph_text_map(p)
    assert text == "(1) x"
    fields = dx.fldsimple_fields(p, segs)
    assert len(fields) == 1
    assert "ZOTERO_ITEM" in fields[0].instr
    assert fields[0].span == (0, 3)


def test_unclosed_field_ignored_and_instr_not_leaking():
    p = para(
        run('<w:fldChar w:fldCharType="begin"/>')
        + run("<w:instrText> ZOTERO_BIBL {} CSL_BIBLIOGRAPHY </w:instrText>")
        + run('<w:fldChar w:fldCharType="separate"/>')
        + run("<w:t>Vaswani A. Attention is all you need. 2017.</w:t>")
        # no end fldChar: bibliography fields span multiple paragraphs
    )
    text, _ = dx.paragraph_text_map(p)
    assert text == "Vaswani A. Attention is all you need. 2017."
    assert dx.paragraph_fields(p) == []  # unclosed -> not a citation field


def test_superscript_run():
    p = para(
        run("<w:t>text</w:t>")
        + run("<w:t>1,3</w:t>", '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>')
    )
    _, segs = dx.paragraph_text_map(p)
    assert dx.is_superscript_run(segs[0].run) is False
    assert dx.is_superscript_run(segs[1].run) is True


def test_iter_paragraphs_includes_table_cells():
    doc = etree.fromstring(
        f'<w:document {W}><w:body>'
        "<w:p><w:r><w:t>a</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "<w:p><w:r><w:t>b</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    ids = [pid for pid, _ in dx.iter_paragraphs(doc)]
    texts = [dx.paragraph_text_map(p)[0] for _, p in dx.iter_paragraphs(doc)]
    assert ids == ["p0", "p1", "p2"]
    assert texts == ["a", "cell", "b"]


def test_style_helpers():
    p = para(
        '<w:pPr><w:pStyle w:val="1"/><w:outlineLvl w:val="0"/></w:pPr>'
        + run("<w:t>h</w:t>")
    )
    assert dx.paragraph_style_id(p) == "1"
    assert dx.paragraph_outline_lvl(p) == 0
