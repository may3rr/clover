"""Heading detection: styles.xml resolution, regex fallback, canonical map."""

from lxml import etree

from citecheck.parse import docx_xml as dx
from citecheck.parse import headings as hd

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def styles_xml(body: str) -> etree._Element:
    return etree.fromstring(f"<w:styles {W}>{body}</w:styles>")


def para(inner: str) -> etree._Element:
    return etree.fromstring(f'<w:p {W}>{inner}</w:p>')


def style(sid: str, name: str, extra: str = "") -> str:
    return (
        f'<w:style w:styleId="{sid}" w:type="paragraph">'
        f'<w:name w:val="{name}"/>{extra}</w:style>'
    )


def test_english_heading_style():
    styles = hd.load_styles(styles_xml(style("Heading1", "heading 1")))
    p = para('<w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>1 Introduction</w:t></w:r>')
    assert hd.heading_level(p, "1 Introduction", styles) == 1


def test_localized_style_id_and_name():
    # Chinese Word: styleId "2", w:name "heading 2"
    styles = hd.load_styles(
        styles_xml(style("1", "heading 1") + style("2", "heading 2"))
    )
    p = para('<w:pPr><w:pStyle w:val="2"/></w:pPr><w:r><w:t>2.1 方法概述</w:t></w:r>')
    assert hd.heading_level(p, "2.1 方法概述", styles) == 2


def test_outline_lvl_on_paragraph_and_based_on_chain():
    styles = hd.load_styles(
        styles_xml(
            style("MyHead", "my custom heading", '<w:basedOn w:val="H1"/>')
            + style("H1", "some name", '<w:pPr><w:outlineLvl w:val="1"/></w:pPr>')
        )
    )
    p = para('<w:pPr><w:pStyle w:val="MyHead"/></w:pPr><w:r><w:t>Sect</w:t></w:r>')
    assert hd.heading_level(p, "Sect", styles) == 2  # outlineLvl 1 -> level 2
    p2 = para('<w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>Direct</w:t></w:r>')
    assert hd.heading_level(p2, "Direct", styles) == 1


def test_regex_fallback_headings():
    styles = {}
    assert hd.heading_level(para("<w:r><w:t>1 引言</w:t></w:r>"), "1 引言", styles) == 1
    assert hd.heading_level(para("<w:r><w:t>2. Related Work</w:t></w:r>"), "2. Related Work", styles) == 1
    assert hd.heading_level(para("<w:r><w:t>3.1 Architecture</w:t></w:r>"), "3.1 Architecture", styles) == 2
    assert hd.heading_level(para("<w:r><w:t>一、引言</w:t></w:r>"), "一、引言", styles) == 1


def test_regex_rejects_prose():
    styles = {}
    long_text = "1 " + "x" * 80
    assert hd.heading_level(para(""), long_text, styles) is None
    assert hd.heading_level(para(""), "2019 年，Devlin 等人提出了 BERT 模型。", styles) is None
    assert hd.heading_level(para(""), "3.14 is the value of pi.", styles) is None


def test_canonical_mapping():
    assert hd.canonical_for("1 Introduction") == "intro"
    assert hd.canonical_for("2. Related Work") == "related"
    assert hd.canonical_for("研究方法") == "method"
    assert hd.canonical_for("4 Experiments and Results") == "experiment"
    assert hd.canonical_for("Discussion") == "discussion"
    assert hd.canonical_for("6 Conclusion and Future Work") == "conclusion"
    assert hd.canonical_for("附录") == "other"


def test_ref_heading():
    assert hd.is_ref_heading("References")
    assert hd.is_ref_heading("参考文献")
    assert hd.is_ref_heading("7. Bibliography")
    assert hd.is_ref_heading("Works Cited")
    assert not hd.is_ref_heading("Reference implementation")
    assert not hd.is_ref_heading("引言")
