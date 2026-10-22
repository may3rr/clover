"""Smoke tests on a real (unpublished) Chinese manuscript and its PDF
folder. The files never enter the repo — point the env vars at them:

    CLOVER_ZH_PAPER=/path/paper.docx CLOVER_ZH_LIBRARY=/path/ref pytest tests/test_real_zh.py
"""

import os
from pathlib import Path

import pytest

from citecheck.parse import parse_docx

PAPER = os.environ.get("CLOVER_ZH_PAPER")
LIBRARY = os.environ.get("CLOVER_ZH_LIBRARY")

needs_paper = pytest.mark.skipif(
    not PAPER or not Path(PAPER).exists(), reason="CLOVER_ZH_PAPER not set")


@needs_paper
def test_real_paper_parses():
    doc = parse_docx(PAPER)
    assert len(doc.references) >= 10
    labels = [int(r.label) for r in doc.references if r.label]
    assert labels == list(range(1, len(labels) + 1))
    linked = [m for m in doc.markers if m.ref_ids]
    assert len(linked) / len(doc.markers) >= 0.95
    # every reference is cited somewhere, no marker points outside the list
    cited = {rid for m in doc.markers for rid in m.ref_ids}
    assert cited == {r.id for r in doc.references}


needs_library = pytest.mark.skipif(
    not LIBRARY or not Path(LIBRARY).exists(), reason="CLOVER_ZH_LIBRARY not set")


@needs_library
def test_real_library_metadata(tmp_path):
    from citecheck.cache import Cache
    from citecheck.library.scan import scan_folder

    pdfs = scan_folder(LIBRARY, Cache(tmp_path / "c.sqlite"))
    # every CNKI download yields title + authors from the cover or 引用本文
    cnki = [p for p in pdfs if p.doc.source in {"cnki_cover", "cnki_citation"}]
    assert len(cnki) >= len(pdfs) - 1
    assert all(p.doc.title and p.doc.authors and p.doc.year for p in cnki)
