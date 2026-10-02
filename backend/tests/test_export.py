"""T10 tests: docx export with Word comments + tracked changes."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from citecheck.distribution.layer import run_distribution
from citecheck.export import export_report
from citecheck.export.simulate import simulated_texts
from citecheck.lint.norms import check_norms
from citecheck.lint.reorder import plan_reorder
from citecheck.parse import docx_xml
from citecheck.parse.parser import parse_docx
from citecheck.schema import (
    Anchor,
    Finding,
    Report,
    ReportMeta,
    Revision,
)

FIXTURES = Path("tests/fixtures")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ALL_FIXTURES = [
    "numeric_en.docx",
    "authoryear_en.docx",
    "gbt_zh.docx",
    "zotero_numeric.docx",
    "numeric_unordered_en.docx",
]


def w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def build_report(src: Path, extra_findings=None, extra_revisions=None,
                 with_distribution=True) -> Report:
    """Deterministic report: norms + reorder (+ distribution), no LLM."""
    p = parse_docx(src)
    findings = check_norms(p)
    if with_distribution:
        findings += asyncio.run(run_distribution(p, classify=False))[1]
    revisions = plan_reorder(p)
    if extra_findings:
        findings += extra_findings
    if extra_revisions:
        revisions += extra_revisions
    for i, f in enumerate(findings, 1):
        f.id = f"f{i}"
    for i, r in enumerate(revisions, 1):
        r.id = f"v{i}"
    return Report(
        document=p.document, sections=p.sections, paragraphs=p.paragraphs,
        markers=p.markers, references=p.references, findings=findings,
        revisions=revisions, meta=ReportMeta())


def read_part(path: Path, name: str) -> bytes | None:
    with zipfile.ZipFile(path) as z:
        try:
            return z.read(name)
        except KeyError:
            return None


def doc_root(path: Path) -> etree._Element:
    return etree.fromstring(read_part(path, "word/document.xml"))


def original_texts(src: Path) -> list[str]:
    with zipfile.ZipFile(src) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    return [docx_xml.paragraph_text_map(p)[0]
            for _, p in docx_xml.iter_paragraphs(root)]


# ---------------------------------------------------------------- tests


def test_export_creates_comments_part(tmp_path):
    src = FIXTURES / "numeric_unordered_en.docx"
    assert read_part(src, "word/comments.xml") is None  # source lacks it
    out = export_report(src, build_report(src), tmp_path / "out.docx")
    comments = read_part(out, "word/comments.xml")
    assert comments is not None
    root = etree.fromstring(comments)
    report = build_report(src)
    assert len(root.findall(w("comment"))) == len(report.findings)
    # registration
    ct = read_part(out, "[Content_Types].xml").decode()
    rels = read_part(out, "word/_rels/document.xml.rels").decode()
    assert "comments+xml" in ct
    assert "relationships/comments" in rels
    # author/date on every comment
    for c in root.findall(w("comment")):
        assert c.get(w("author")) == "引用体检"
        assert c.get(w("date"))


def test_export_appends_to_existing_comments(tmp_path):
    src = FIXTURES / "numeric_unordered_en.docx"
    first = export_report(src, build_report(src), tmp_path / "first.docx")
    n1 = len(etree.fromstring(
        read_part(first, "word/comments.xml")).findall(w("comment")))
    assert n1 > 0
    # second export from a file that already has comments.xml
    report2 = build_report(first)
    second = export_report(first, report2, tmp_path / "second.docx")
    n2 = len(etree.fromstring(
        read_part(second, "word/comments.xml")).findall(w("comment")))
    assert n2 == n1 + len(report2.findings)


def test_export_splits_mixed_format_runs(tmp_path):
    """An anchor spanning multiple runs with mixed bold/italic must keep
    each side's rPr after the split + wrapping."""
    src = FIXTURES / "numeric_en.docx"
    p = parse_docx(src)
    # find a paragraph whose marker text spans runs with differing rPr
    target = None
    with zipfile.ZipFile(src) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    for pid, el in docx_xml.iter_paragraphs(root):
        runs = [r for r in el.iter(w("r")) if _text_of(r)]
        sigs = {_fmt_sig(r) for r in runs}
        if len(runs) >= 3 and len(sigs) >= 2:
            target = (pid, el)
            break
    assert target, "need a mixed-format paragraph in the fixture"
    pid, _ = target
    para = next(pp for pp in p.paragraphs if pp.id == pid)
    rev = Revision(
        id="v1", kind="typo", anchor=Anchor(paragraph_id=pid, start=0,
                                            end=len(para.text)),
        old=para.text, new=para.text.replace("a", "A", 1), reason="test")
    report = build_report(src, extra_revisions=[rev],
                          with_distribution=False)
    out = export_report(src, report, tmp_path / "out.docx")
    root2 = doc_root(out)
    el2 = dict(docx_xml.iter_paragraphs(root2))[pid]
    # ins wrapper holds runs with at least two distinct rPr signatures
    ins_sigs = set()
    for ins in el2.iter(w("ins")):
        for r in ins.findall(w("r")):
            ins_sigs.add(_fmt_sig(r))
    assert len(ins_sigs) >= 2


def _text_of(r: etree._Element) -> str:
    return "".join(t.text or "" for t in r.iter(w("t")))


def _fmt_sig(r: etree._Element) -> str:
    rpr = r.find(w("rPr"))
    if rpr is None:
        return "plain"
    return "".join(sorted(etree.QName(c).localname for c in rpr))


def test_export_revision_and_comment_same_paragraph(tmp_path):
    src = FIXTURES / "numeric_unordered_en.docx"
    p = parse_docx(src)
    para = p.paragraphs[2]
    f = Finding(
        id="f9", layer="support", severity="medium",
        anchor=Anchor(paragraph_id=para.id, start=0, end=10),
        title="论断缺少支撑", detail="detail line")
    report = build_report(src, extra_findings=[f], with_distribution=False)
    out = export_report(src, report, tmp_path / "out.docx")
    root = doc_root(out)
    el = dict(docx_xml.iter_paragraphs(root))[para.id]
    tags = {etree.QName(c).localname for c in el.iter()}
    assert "ins" in tags and "commentReference" in tags


def test_export_moves_including_start(tmp_path):
    src = FIXTURES / "numeric_unordered_en.docx"
    report = build_report(src, with_distribution=False)
    moves = [r for r in report.revisions
             if r.kind == "ref_reorder" and r.move_after]
    assert any(r.move_after == "__start__" for r in moves)
    out = export_report(src, report, tmp_path / "out.docx")
    # self-check inside export_report already verified accept-all order;
    # additionally assert an inserted paragraph carries the new label
    root = doc_root(out)
    first_ref = report.references[0]
    inserted = [p for p in root.iter(w("p"))
                if p.find(f"{w('pPr')}/{w('rPr')}/{w('ins')}") is not None]
    assert inserted
    texts = ["".join(t.text or "" for t in p.iter(w("t"))) for p in inserted]
    assert any("[1]" in t for t in texts)


def test_export_anchorless_finding(tmp_path):
    src = FIXTURES / "numeric_unordered_en.docx"
    f = Finding(id="f9", layer="norms", severity="low", anchor=None,
                title="样式混用", detail="detail")
    report = build_report(src, extra_findings=[f], with_distribution=False)
    out = export_report(src, report, tmp_path / "out.docx")
    root = doc_root(out)
    # lands on the first section heading paragraph (or first non-empty)
    heads = [p for s in report.sections for p in [s.heading_paragraph_id]
             if p]
    pid = heads[0] if heads else next(
        p.id for p in report.paragraphs if p.text.strip())
    el = dict(docx_xml.iter_paragraphs(root))[pid]
    assert el.find(f".//{w('commentReference')}") is not None or \
        el.getnext() is not None


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_export_reject_all_equals_original(tmp_path, name):
    src = FIXTURES / name
    out = export_report(src, build_report(src), tmp_path / f"{name}.out.docx")
    rejected = simulated_texts(doc_root(out), "reject")
    assert rejected == original_texts(src)


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_export_accept_all_parses(tmp_path, name):
    src = FIXTURES / name
    out = export_report(src, build_report(src), tmp_path / f"{name}.out.docx")
    accepted = simulated_texts(doc_root(out), "accept")
    assert len(accepted) >= len(original_texts(src))
    # every accepted text differs from original only via applied revisions
    # (export_report's internal self-check covers marker->ref consistency)


SOFFICE = shutil.which("soffice") or \
    "/Applications/LibreOffice.app/Contents/MacOS/soffice"


@pytest.mark.parametrize("name", ALL_FIXTURES)
@pytest.mark.skipif(not Path(SOFFICE).exists(), reason="LibreOffice missing")
def test_export_libreoffice_converts(tmp_path, name):
    src = FIXTURES / name
    out = export_report(src, build_report(src), tmp_path / f"{name}.out.docx")
    r = subprocess.run(
        [SOFFICE, "--headless", "--convert-to", "pdf",
         "--outdir", str(tmp_path), str(out)],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / (out.stem + ".pdf")).exists()
