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
    titled = [s for s in numeric.sections if s.title and s.title != "Abstract"]
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
    # natbib 的 \bibitem[Short(Year)] 标签就是 LaTeX 实际印出的文本
    assert "(Lewis et al., 2020)" in ay
    assert "Vaswani et al." in ay     # \citeauthor 只出名字
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


# ---------------------------------------------------------------- 鲁棒性

def test_robustness_edge_cases(tmp_path):
    """真实文章里的变体：导言区 addbibresource、无括号 \\input、
    \\verb 里的 %、\\let/\\newcommand 别名、\\iffalse 块。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage[style=authoryear]{biblatex}\n"
        "\\addbibresource{refs.bib}\n"
        "\\let\\mycite\\citep\n"
        "\\newcommand{\\scite}[1]{\\textcite{#1}}\n"
        "\\begin{document}\n"
        "\\section{Intro}\n"
        "Citing \\cite{a1} and \\mycite{b2} and \\scite{c3}.\n"
        "\\input sub\n"
        "Code \\verb|a%b| stays.\n"
        "\\iffalse hidden \\cite{ghost}\n\\fi\n"
        "\\end{document}\n")
    (tmp_path / "sub.tex").write_text(
        "\\section{Method}\nWe follow \\citep{a1}.\n")
    (tmp_path / "refs.bib").write_text(
        "@article{a1, author={A}, title={T1}, year={2001}}\n"
        "@article{b2, author={B}, title={T2}, year={2002}}\n"
        "@article{c3, author={C}, title={T3}, year={2003}}\n")

    d = parse_latex(tmp_path)
    texts = [p.text for p in d.paragraphs]
    keys = {k for m in d.markers for k in m.keys}
    assert keys == {"a1", "b2", "c3"}          # 别名都算引用
    assert {r.key for r in d.references} == {"a1", "b2", "c3"}
    assert any("a%b stays" in t for t in texts)  # \verb 内 % 非注释
    assert not any("hidden" in t for t in texts)  # \iffalse 丢弃
    assert any("Method" == s.title for s in d.sections)


def test_filecontents_embedded_bib(tmp_path):
    """filecontents 自包含 .bib（arXiv 单文件提交常见）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage[numbers]{natbib}\n"
        "\\begin{filecontents}{embedded.bib}\n"
        "@article{a1, author={A}, title={T}, year={2020}, journal={J}}\n"
        "\\end{filecontents}\n"
        "\\begin{document}\n"
        "Text \\citep{a1}.\n"
        "\\bibliographystyle{plainnat}\n"
        "\\bibliography{embedded}\n"
        "\\end{document}\n")
    d = parse_latex(tmp_path)
    assert [r.key for r in d.references] == ["a1"]
    assert d.markers[0].ref_ids == ["r1"]


# ---------------------------------------------------------------- archives

import io
import tarfile
import zipfile as _zip

from citecheck.parse.latex.archive import ArchiveError, extract_archive
from citecheck.parse.latex.locate import Locator


def _zip_project(tmp_path, files: dict[str, str], name="paper.zip"):
    z = tmp_path / name
    with _zip.ZipFile(z, "w") as zf:
        for rel, text in files.items():
            zf.writestr(rel, text)
    return z


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Archives extract under the cache dir — keep tests out of the real one."""
    from citecheck.parse.latex import archive
    base = tmp_path / "extract"
    real = archive.extract_archive
    monkeypatch.setattr(
        "citecheck.parse.latex.parser.extract_archive",
        lambda p: real(p, base))
    return base


def test_zip_with_wrapper_folder(tmp_path, cache_dir):
    """Typical Overleaf download: one top-level folder, main file inside."""
    src = FIXTURES / "latex_numeric"
    files = {f"proj/{p.name}": p.read_text() for p in src.iterdir()}
    files["proj/figs/plot.tex"] = "\\begin{tikzpicture}\\end{tikzpicture}"
    d = parse_document(_zip_project(tmp_path, files))
    assert d.document.source_format == "tex"
    assert d.document.filename == "paper.zip"
    assert d.document.title == "Measuring Citation Recall"
    assert d.latex.main == "proj/main.tex"
    assert len(d.references) == 3


def test_targz_and_single_gz(tmp_path, cache_dir):
    main = (FIXTURES / "latex_authoryear.tex").read_bytes()
    tgz = tmp_path / "2101.00001.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        info = tarfile.TarInfo("ms.tex")
        info.size = len(main)
        tf.addfile(info, io.BytesIO(main))
    assert parse_document(tgz).document.title == "An Author-Year Study"
    import gzip
    gz = tmp_path / "2101.00002.gz"   # arXiv single-file e-print
    gz.write_bytes(gzip.compress(main))
    assert parse_document(gz).document.title == "An Author-Year Study"


def test_zip_slip_and_symlinks_skipped(tmp_path):
    z = tmp_path / "evil.zip"
    with _zip.ZipFile(z, "w") as zf:
        zf.writestr("../escape.tex", "x")
        zf.writestr("/abs.tex", "x")
        zf.writestr("__MACOSX/._main.tex", "x")
        link = _zip.ZipInfo("link.tex")
        link.external_attr = (0o120777 << 16)
        zf.writestr(link, "/etc/passwd")
        zf.writestr("main.tex", "\\documentclass{article}")
    out = extract_archive(z, tmp_path / "x")
    names = sorted(p.relative_to(out).as_posix()
                   for p in out.rglob("*") if p.is_file())
    assert names == [".clover-extracted", "main.tex"]
    assert not (tmp_path / "escape.tex").exists()


def test_bad_archive(tmp_path):
    bad = tmp_path / "broken.zip"
    bad.write_bytes(b"PK\x03\x04 not really")
    with pytest.raises(ArchiveError):
        extract_archive(bad, tmp_path / "x")


# ---------------------------------------------------------------- mapping

def test_source_mapping_points_at_original_text(numeric):
    """Every rendered character of plain prose maps back to the same
    character in the original file — including through \\input."""
    loc = Locator(numeric.latex)
    root = Path(numeric.latex.root)
    checked = 0
    ref_paras = {r.paragraph_id for r in numeric.references}
    for p in numeric.paragraphs:
        if p.id in ref_paras:
            continue
        for word in ("Transformer", "Numbers", "approach", "twist"):
            k = p.text.find(word)
            if k < 0:
                continue
            rel, fpos, exact = loc.offset(p.id, k)
            assert exact
            assert (root / rel).read_text()[fpos:fpos + len(word)] == word
            checked += 1
    assert checked == 4
    marker = next(m for m in numeric.markers if m.keys == ["lewis2020"])
    assert loc.loc(marker.paragraph_id, marker.start) == "method.tex:2"


def test_macros_comments_and_assignments(tmp_path):
    (tmp_path / "main.tex").write_text(r"""\documentclass{article}
\newcommand{\method}{CiteGuard}
\newcommand{\term}[1]{\emph{#1}}
\begin{document}
\section{Intro}
\looseness=-1 We present \method{}, a % trailing comment
  tool for \term{citation checking}.\setlength{\parskip}{2pt}
\end{document}
""")
    d = parse_latex(tmp_path / "main.tex")
    body = next(p.text for p in d.paragraphs if "present" in p.text)
    assert body == "We present CiteGuard, a tool for citation checking."


def test_bbl_only_project(tmp_path):
    """arXiv sources often ship the compiled .bbl without the .bib."""
    (tmp_path / "ms.tex").write_text(r"""\documentclass{article}
\usepackage{natbib}
\begin{document}
\section{Intro}
Attention \citep{vaswani2017} and BERT \citet{devlin2019}.
\bibliographystyle{acl_natbib}
\bibliography{custom}
\end{document}
""")
    (tmp_path / "ms.bbl").write_text(r"""\begin{thebibliography}{2}
\bibitem[{Devlin et~al.(2019)Devlin, Chang, Lee, and Toutanova}]{devlin2019}
Jacob Devlin, Ming-Wei Chang, Kenton Lee, and Kristina Toutanova. 2019.
\newblock BERT: Pre-training of deep bidirectional transformers.
\newblock In \emph{NAACL}.

\bibitem[{Vaswani et~al.(2017)Vaswani, Shazeer, Parmar}]{vaswani2017}
Ashish Vaswani, Noam Shazeer, and Niki Parmar. 2017.
\newblock Attention is all you need.
\newblock In \emph{NeurIPS}.
\end{thebibliography}
""")
    d = parse_latex(tmp_path / "ms.tex")
    assert [r.key for r in d.references] == ["devlin2019", "vaswani2017"]
    assert d.references[1].title == "Attention is all you need"
    raws = [m.raw for m in d.markers]
    assert raws == ["(Vaswani et al., 2017)", "Devlin et al. (2019)"]
    assert all(m.ref_ids for m in d.markers)
    assert d.structured_refs == []  # bbl text → model still structures it
    loc = Locator(d.latex)
    r = d.references[0]
    assert loc.loc(r.paragraph_id, 0) == "ms.bbl:2"


def test_bib_plus_bbl_merges(tmp_path):
    """.bib gives fields, .bbl gives print order and entries the .bib lacks."""
    (tmp_path / "main.tex").write_text(r"""\documentclass{article}
\usepackage[numbers]{natbib}
\begin{document}
See \cite{b,a}.
\bibliographystyle{plain}
\bibliography{refs}
\end{document}
""")
    (tmp_path / "refs.bib").write_text(
        "@article{b, title={Bee Paper}, author={Zed, Z.}, year={2020}}\n")
    (tmp_path / "main.bbl").write_text(r"""\begin{thebibliography}{2}
\bibitem{a} A. Alpha. Alpha paper. 2019.
\bibitem{b} Z. Zed. Bee paper. 2020.
\end{thebibliography}""")
    d = parse_latex(tmp_path / "main.tex")
    assert [r.key for r in d.references] == ["a", "b"]
    assert d.references[1].title == "Bee Paper"      # from .bib
    assert d.structured_refs == [d.references[1].id]
    assert d.markers[0].raw == "[2,1]"


def test_acl_newcite_and_table_citations(tmp_path):
    """ACL's \\newcite is a citation; a \\cite inside a dropped table still
    makes the entry cited (no false 未被引用 finding)."""
    (tmp_path / "main.tex").write_text(r"""\documentclass{article}
\usepackage{natbib}
\begin{document}
\section{Intro}
As shown by~\newcite{a}, things work.
\begin{table}\begin{tabular}{l}Model \cite{b} \\\end{tabular}
\caption{Results.}\end{table}
\begin{thebibliography}{2}
\bibitem[{Alpha(2019)}]{a} A. Alpha. 2019. Alpha paper. Venue.
\bibitem[{Beta(2020)}]{b} B. Beta. 2020. Beta paper. Venue.
\end{thebibliography}
\end{document}
""")
    d = parse_latex(tmp_path / "main.tex")
    assert [m.raw for m in d.markers] == ["Alpha (2019)"]
    assert set(d.cited_keys) == {"a", "b"}
    assert not [f for f in check_norms(d) if "没有被引用" in f.title]


def test_inline_math_spans_and_runs(tmp_path):
    (tmp_path / "main.tex").write_text(r"""\documentclass{article}
\begin{document}
We update $c_{t+1} = (c_t, a_t)$ with $10^3$ steps.
\end{document}
""")
    d = parse_latex(tmp_path / "main.tex")
    p = next(p for p in d.paragraphs if p.text.startswith("We update"))
    assert [p.text[m.start:m.end] for m in p.math] == [
        "c_t+1 = (c_t, a_t)", "10^3"]
    assert p.math[0].runs[:2] == [("c", ""), ("t+1", "sub")]
    assert p.math[1].runs == [("10", ""), ("3", "sup")]


def test_anchor_snippet_points_at_source(numeric):
    from citecheck.parse.latex.locate import annotate_locations
    from citecheck.schema import Anchor
    p = next(p for p in numeric.paragraphs if "twist" in p.text)
    k = p.text.index("twist")
    a = Anchor(paragraph_id=p.id, start=k, end=k + 5)
    annotate_locations(numeric.latex, [a])
    assert a.loc == "method.tex:2"
    assert a.snippet.startswith("Our approach follows \\citet{lewis2020}")
    s, e = a.snippet_hl
    assert a.snippet[s:e] == "twist"


def test_snippet_highlights_whole_cite_command(numeric):
    from citecheck.parse.latex.locate import annotate_locations
    from citecheck.schema import Anchor
    m = next(m for m in numeric.markers if m.keys == ["lewis2020"])
    a = Anchor(paragraph_id=m.paragraph_id, start=m.start, end=m.end)
    annotate_locations(numeric.latex, [a])
    s, e = a.snippet_hl
    assert a.snippet[s:e] == "\\citet{lewis2020}"
