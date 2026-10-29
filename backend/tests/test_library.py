"""Library scan (文献文件夹): metadata, duplicates, scans, CAJ."""

from __future__ import annotations

import pytest

from citecheck.cache import Cache
from citecheck.library.scan import is_arxiv_stamp, scan_folder, unsupported_files
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


# ------------------------------------------------------------ linking

from pathlib import Path  # noqa: E402

from citecheck.library.link import link_library  # noqa: E402
from citecheck.llm import client as llm  # noqa: E402
from citecheck.parse import parse_docx  # noqa: E402
from citecheck.schema import Reference  # noqa: E402

DAKD = Path(__file__).parent / "fixtures" / "dakd_zh.docx"


def _docname(lib, rid):
    link = next((x for x in lib.links if x.ref_id == rid), None)
    if link is None:
        return None
    return next(d.filename for d in lib.docs if d.id == link.doc_id)


@pytest.mark.asyncio
async def test_link_fixture_manuscript(library):
    ref, _, pdfs = library
    refs = parse_docx(DAKD).references
    # blank target: no guessing from the folder, no exemplars
    blank = await link_library(refs, pdfs, str(ref), use_model=False)
    assert blank.venue is None and blank.exemplar_ids == [] and blank.venue_match_ids == []
    lib = await link_library(refs, pdfs, str(ref), use_model=False, venue="数据分析与知识发现")
    assert _docname(lib, "r1").startswith("生成式AI")  # formal CNKI page
    assert _docname(lib, "r2").startswith("Ji et al.")  # not the Siren survey
    assert _docname(lib, "r3").endswith("曾子明.pdf")  # CNKI cover
    assert _docname(lib, "r4") is None  # no PDF for Qwen3
    assert _docname(lib, "r5") == "fact-check.pdf"  # renamed file
    assert all(x.status == "auto" for x in lib.links)
    # the three uncited DAKD papers match the journal; the duplicate is
    # merged, the cited ones and the scan are not candidates. The review
    # (研究现状) is offered but not selected for a research manuscript
    assert lib.venue == "数据分析与知识发现" and lib.venue_source == "user"
    matched = sorted(d.filename for d in lib.docs if d.id in lib.venue_match_ids)
    assert matched == sorted([
        "基于多提示学习的方面级情感分析研究_钱玲飞.pdf",
        "基于分布式认知的多智能体虚假新闻检测研究_邹逢源.pdf",
        "基于大语言模型的命名实体识别研究现状_阮光册.pdf",
    ])
    names = sorted(d.filename for d in lib.docs if d.id in lib.exemplar_ids)
    assert names == sorted([
        "基于多提示学习的方面级情感分析研究_钱玲飞.pdf",
        "基于分布式认知的多智能体虚假新闻检测研究_邹逢源.pdf",
    ])
    review = next(d for d in lib.docs if "研究现状" in d.filename)
    assert review.paper_type == "review" and review.venue_via == "cnki_cover"


@pytest.mark.asyncio
async def test_link_doi_wins_over_title(library):
    ref, _, pdfs = library
    r = Reference(id="r1", raw="x", title="A completely different title here",
                  doi="10.1145/3571730", lang="en")
    lib = await link_library([r], pdfs, str(ref), use_model=False)
    assert _docname(lib, "r1").startswith("Ji et al.")
    assert lib.links[0].method == "doi"


@pytest.mark.asyncio
async def test_mid_band_goes_to_model_and_needs_review(library, monkeypatch):
    ref, _, pdfs = library
    # a mangled title: below the automatic threshold, above the ask band
    r = Reference(id="r9", raw="韩明星. 融合蕴含树与大模型的事实核查方法研究[J]. 数据分析与知识发现, 2026.",
                  title="融合蕴含树与大模型的事实核查方法研究", authors=["韩明星"],
                  year=2026, lang="zh")
    seen = {}

    async def fake(task, messages, schema, **kw):
        seen["prompt"] = messages[0]["content"]
        return llm.LLMResult(value=schema(choice=1), route="cloud")

    monkeypatch.setattr(llm, "chat_json", fake)
    lib = await link_library([r], pdfs, str(ref))
    assert _docname(lib, "r9") == "fact-check.pdf"
    assert "融合蕴含树和LLM的事实核查研究" in seen["prompt"]
    assert lib.links[0].method == "llm" and lib.links[0].status == "review"

    async def none(task, messages, schema, **kw):
        return llm.LLMResult(value=schema(choice=0), route="cloud")

    monkeypatch.setattr(llm, "chat_json", none)
    lib = await link_library([r], pdfs, str(ref))
    assert lib.links == []


def test_arxiv_margin_stamp_is_not_a_title():
    assert is_arxiv_stamp("arXiv:1711.01731v3 [cs.CL] 11 Jan 2018")
    assert is_arxiv_stamp("arXiv:1408.5882 [cs.CL]")
    assert not is_arxiv_stamp("A Survey on Dialogue Systems: Recent Advances and New Frontiers")
