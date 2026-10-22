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
