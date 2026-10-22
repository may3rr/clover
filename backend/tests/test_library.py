"""Library scan (文献文件夹): metadata, duplicates, scans, CAJ."""

from __future__ import annotations

import pytest

from citecheck.cache import Cache
from citecheck.library.scan import scan_folder, unsupported_files
from citecheck.library.text import clean_page, squash_cjk_spaces
from libgen import build_library


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    root = tmp_path_factory.mktemp("lib")
    ref = build_library(root)
    cache = Cache(root / "cache.sqlite")
    return ref, cache, scan_folder(ref, cache)


def _by_name(pdfs, needle):
    return next(p for p in pdfs if needle in p.doc.filename)


def test_cjk_space_squash():
    assert squash_cjk_spaces("代 伟 1 朱行策") == "代伟1朱行策"
    assert squash_cjk_spaces("达到 0 . 259 和 0 . 494") == "达到0.259和0.494"
    assert clean_page("生成内容在语言上流\n畅，在事实上\nnot always") == \
        "生成内容在语言上流畅，在事实上not always"
    assert clean_page("［Ｊ］．２０２２") == "[J]．2022"


def test_cnki_cover(library):
    _, _, pdfs = library
    p = _by_name(pdfs, "曾子明")
    assert p.doc.source == "cnki_cover"
    assert p.doc.title == "面向古典文学问答领域的大语言模型对抗幻觉优化方法研究"
    assert p.doc.authors == ["曾子明", "徐康"]
    assert p.doc.venue == "数据分析与知识发现" and p.doc.year == 2026
    assert p.cover_pages == 1
    body, starts = p.body()
    assert "网络首发" not in body and starts[0] == 0 and len(starts) == 2


def test_renamed_file_still_read_from_content(library):
    _, _, pdfs = library
    p = _by_name(pdfs, "fact-check")
    assert p.doc.title == "融合蕴含树和LLM的事实核查研究"
    assert p.doc.authors[0] == "韩明星"


def test_formal_cnki_citation(library):
    _, _, pdfs = library
    p = _by_name(pdfs, "王静静")
    assert p.doc.source == "cnki_citation"
    assert p.doc.title == "生成式AI及其GPT类技术应用对信息管理与传播的变革探析"
    assert p.doc.venue == "中国图书馆学报" and p.doc.year == 2023
    assert p.doc.authors[:2] == ["王静静", "叶鹰"]


def test_english_layout_title_and_doi(library):
    _, _, pdfs = library
    p = _by_name(pdfs, "Ji et al.")
    assert p.doc.source == "layout"
    assert p.doc.title == "Survey of Hallucination in Natural Language Generation"
    assert p.doc.doi == "10.1145/3571730"


def test_duplicates_merged(library):
    _, _, pdfs = library
    names = [p.doc.filename for p in pdfs]
    assert "基于多提示学习的方面级情感分析研究_钱玲飞.pdf" in names
    assert not any("(1)" in n for n in names)
    p = _by_name(pdfs, "钱玲飞")
    assert p.doc.duplicates == ["基于多提示学习的方面级情感分析研究_钱玲飞 (1).pdf"]


def test_scan_unreadable_and_caj(library):
    ref, _, pdfs = library
    assert _by_name(pdfs, "scan.pdf").doc.readable is False
    assert unsupported_files(ref) == ["old.caj"]


def test_cached_rescan(library):
    ref, cache, pdfs = library
    again = scan_folder(ref, cache)
    assert [p.doc for p in again] == [p.doc for p in pdfs]
