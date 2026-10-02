"""LaTeX 项目解析测试。

fixtures/latex_numeric/ 是 .bib + \\input 的目录项目（natbib numbers），
fixtures/latex_authoryear.tex 是内嵌 thebibliography 的单文件
（natbib 默认作者-年份）。引用键直连条目，链接必须 100% 精确。
"""

import json
from pathlib import Path

import pytest

from citecheck.lint.norms import check_norms
from citecheck.parse import parse_document, parse_latex

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def numeric():
    return parse_latex(FIXTURES / "latex_numeric")


@pytest.fixture(scope="module")
def authoryear():
    return parse_document(FIXTURES / "latex_authoryear.tex")


# ---------------------------------------------------------------- dispatch

def test_dispatch_dir_and_tex(numeric, authoryear):
    assert numeric.document.source_format == "tex"
    assert authoryear.document.source_format == "tex"
    assert parse_document(FIXTURES / "latex_numeric").document.filename == \
        "latex_numeric"
    assert authoryear.document.filename == "latex_authoryear.tex"


def test_styles(numeric, authoryear):
    assert numeric.document.citation_style == "numeric"
    assert authoryear.document.citation_style == "author_year"
    assert numeric.document.title == "Measuring Citation Recall"
    assert authoryear.document.title == "An Author-Year Study"


# ---------------------------------------------------------------- structure

def test_include_expanded_and_sections(numeric):
    titled = [s for s in numeric.sections if s.title]
    assert [s.title for s in titled] == [
        "Introduction", "Method", "Results", "References"]
    assert [s.canonical for s in titled[:3]] == ["intro", "method", "experiment"]


def test_refs_from_bib_only_cited(numeric):
    """.bib 里没被 \\cite/\\nocite 点名的条目不进列表。"""
    assert {r.key for r in numeric.references} == {
        "vaswani2017", "devlin2019", "lewis2020"}
    # numeric：按首次引用顺序编号
    assert [r.key for r in numeric.references] == [
        "devlin2019", "vaswani2017", "lewis2020"]
    assert [r.label for r in numeric.references] == ["1", "2", "3"]


def test_bib_fields(numeric):
    devlin = next(r for r in numeric.references if r.key == "devlin2019")
    assert devlin.title.startswith("BERT")
    assert devlin.year == 2019
    assert devlin.doi == "10.18653/v1/N19-1423"
    assert devlin.authors == ["Devlin, Jacob", "Chang, Ming-Wei"]
    assert devlin.venue == "NAACL-HLT"


def test_bibitem_fields(authoryear):
    lewis = next(r for r in authoryear.references if r.key == "lewis2020")
    assert lewis.title == \
        "Retrieval-augmented generation for knowledge-intensive NLP tasks"
    assert lewis.year == 2020
    assert lewis.venue == "NeurIPS"
    assert lewis.authors == ["Lewis, P.", "Perez, E."]
    # author_year 不用数字标签
    assert all(r.label is None for r in authoryear.references)
    # thebibliography 里所有 bibitem 都在列表内（包括未被引用的）
    assert {r.key for r in authoryear.references} == {
        "lewis2020", "vaswani2017", "uncited2020"}


# ---------------------------------------------------------------- markers

def test_marker_offsets_and_links(numeric, authoryear):
    for doc in (numeric, authoryear):
        by_id = {p.id: p for p in doc.paragraphs}
        for m in doc.markers:
            para = by_id[m.paragraph_id]
            assert para.text[m.start:m.end] == m.raw, (m.id, m.raw)
            assert m.kind == "cite_key"
            # 键一一对应：每个已解析键都能反查到 ref
            keymap = {r.key: r.id for r in doc.references if r.key}
            want = [keymap[k] for k in m.keys if k in keymap]
            assert m.ref_ids == want


def test_marker_rendering(numeric, authoryear):
    num_raws = [m.raw for m in numeric.markers]
    assert "[1]" in num_raws and "[2]" in num_raws
    # \\cite{a,b} 双键一个标记
    assert "[1,2]" in num_raws or "[2,1]" in num_raws
    # 未定义键渲染成 LaTeX 实际的 [?]
    assert "[?]" in num_raws
    # author_year：\\citep → (Name, year)，\\citet → Name (year)
    ay = {m.raw for m in authoryear.markers}
    assert "(Lewis & Perez, 2020)" in ay
    assert "Vaswani & Shazeer" in ay  # \citeauthor 只出名字
    assert "2017" in ay               # \citeyear 只出年份
    assert "(?)" in ay                # 未定义键


# ---------------------------------------------------------------- norms

def test_missing_key_flagged(numeric):
    missing = [f for f in check_norms(numeric)
               if f.title == "正文引用找不到对应的参考文献条目"]
    assert len(missing) == 1
    assert "ghost2024" in missing[0].detail


def test_bib_uncited_not_flagged(numeric):
    """.bib 中未被引用的条目本来就不进参考文献表，不算"未引用"。"""
    uncited = [f for f in check_norms(numeric)
               if "没有被引用" in f.title]
    assert uncited == []


def test_bibitem_uncited_flagged(authoryear):
    uncited = [f for f in check_norms(authoryear)
               if "没有被引用" in f.title]
    assert len(uncited) == 1
    assert uncited[0].refs == ["r3"]


def test_no_reorder_revisions(numeric):
    from citecheck.lint.reorder import plan_reorder
    assert plan_reorder(numeric) == []


def test_no_markers_in_bibliography(numeric, authoryear):
    for doc in (numeric, authoryear):
        ref_paras = {r.paragraph_id for r in doc.references}
        for m in doc.markers:
            assert m.paragraph_id not in ref_paras


def test_json_roundtrip(numeric):
    """ParsedDocument 全部模型可序列化（前端消费）。"""
    json.dumps(numeric.model_dump(mode="json"))
