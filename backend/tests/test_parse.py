"""Fixture-level parsing tests.

Each fixture ships a <name>.expected.json with ground truth: marker raw
texts and expected ref_ids in document order, section canonical mapping,
reference count, citation style and managed_by.
"""

import hashlib
import json
from pathlib import Path

import pytest

from citecheck.parse import parse_docx

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = ["numeric_en", "authoryear_en", "gbt_zh", "zotero_numeric"]


@pytest.fixture(params=NAMES, ids=NAMES, scope="module")
def parsed(request):
    name = request.param
    path = FIXTURES / f"{name}.docx"
    sha_before = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = parse_docx(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha_before
    expected = json.loads((FIXTURES / f"{name}.expected.json").read_text())
    return name, doc, expected


def test_counts(parsed):
    name, doc, exp = parsed
    assert len(doc.references) == exp["reference_count"], name
    assert len(doc.markers) == len(exp["markers"]), name


def test_link_accuracy(parsed):
    name, doc, exp = parsed
    want = exp["markers"]
    assert len(doc.markers) == len(want), name
    correct = sum(
        1
        for m, w in zip(doc.markers, want)
        if m.raw == w["raw"] and m.ref_ids == w["ref_ids"]
    )
    acc = correct / len(want)
    assert acc >= 0.95, f"{name}: link accuracy {acc:.0%}"


def test_sections(parsed):
    name, doc, exp = parsed
    got = [(s.title, s.canonical) for s in doc.sections]
    want = [(s["title"], s["canonical"]) for s in exp["sections"]]
    # leading section (pre-heading text) may appear in got but not want
    got = [g for g in got if g[0]]
    assert got == want, name


def test_marker_offsets(parsed):
    name, doc, _ = parsed
    by_id = {p.id: p for p in doc.paragraphs}
    for m in doc.markers:
        para = by_id[m.paragraph_id]
        assert para.text[m.start : m.end] == m.raw, (
            f"{name} {m.id}: offset mismatch for {m.raw!r}"
        )


def test_document_meta(parsed):
    name, doc, exp = parsed
    assert doc.document.citation_style == exp["citation_style"], name
    assert doc.document.managed_by == exp["managed_by"], name
    assert doc.document.title, name
    assert doc.document.word_count > 0


def test_no_markers_inside_reference_list(parsed):
    name, doc, _ = parsed
    ref_paras = {r.paragraph_id for r in doc.references}
    for m in doc.markers:
        assert m.paragraph_id not in ref_paras, name


def test_references_have_paragraph_anchors(parsed):
    name, doc, _ = parsed
    para_text = {p.id: p.text for p in doc.paragraphs}
    for r in doc.references:
        assert r.paragraph_id in para_text, name
        assert r.raw == para_text[r.paragraph_id].strip(), name


def test_zotero_managed_by():
    doc = parse_docx(FIXTURES / "zotero_numeric.docx")
    assert doc.document.managed_by == "zotero"


def test_chinese_refs_tagged_zh():
    doc = parse_docx(FIXTURES / "gbt_zh.docx")
    assert all(r.lang == "zh" for r in doc.references)
    assert all(r.year for r in doc.references)
