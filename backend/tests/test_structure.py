"""Heuristic field extraction from raw reference strings."""

from citecheck.refs.structure import extract_label, parse_reference


def test_numeric_label_and_fields():
    info = parse_reference(
        "[2] Devlin J, Chang M-W, Lee K, Toutanova K. BERT: Pre-training of "
        "deep bidirectional transformers for language understanding. "
        "Proceedings of NAACL-HLT. 2019:4171-4186. doi:10.18653/v1/N19-1423."
    )
    assert info["label"] == "2"
    assert info["year"] == 2019
    assert info["lang"] == "en"
    assert info["doi"] == "10.18653/v1/N19-1423"
    assert info["authors"][0] == "Devlin J"
    assert "BERT" in info["title"]
    assert info["venue"] == "Proceedings of NAACL-HLT"


def test_bare_number_label():
    assert extract_label("12. Some entry") == "12"
    assert extract_label("[3] Some entry") == "3"
    assert extract_label("Vaswani A. Attention.") is None


def test_apa_author_year():
    info = parse_reference(
        "Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: "
        "Pre-training of deep bidirectional transformers for language "
        "understanding. Proceedings of NAACL-HLT, 4171-4186."
    )
    assert info["year"] == 2019
    assert info["authors"][0] == "Devlin, J."
    assert info["title"].startswith("BERT")


def test_gbt7714_chinese():
    info = parse_reference(
        "[1] 刘知远, 孙茂松, 林衍凯, 等. 知识表示学习研究进展[J]. "
        "计算机研究与发展, 2016, 53(2): 247-261."
    )
    assert info["label"] == "1"
    assert info["lang"] == "zh"
    assert info["year"] == 2016
    assert info["title"] == "知识表示学习研究进展"
    assert "等" not in info["authors"]
    assert info["venue"] == "计算机研究与发展"


def test_edition_chunk_not_venue():
    info = parse_reference(
        "[2] 宗成庆. 统计自然语言处理[M]. 2版. 北京: 清华大学出版社, 2013."
    )
    assert info["title"] == "统计自然语言处理"
    assert info["venue"] != "2版"
    assert info["year"] == 2013
