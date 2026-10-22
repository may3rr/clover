"""文献文件夹 end to end: folder layout, local verification, local
evidence in the support layer, the /library/scan endpoint."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from citecheck.cache import Cache
from citecheck.library.folder import resolve_folder
from citecheck.library.scan import scan_folder
from citecheck.library.source import apply_local, local_source, page_of
from citecheck.schema import RefCheck, Reference
from citecheck.support.evidence import locate_evidence
from libgen import build_library
from test_pipeline import _client, _empty_transport, _patch_llm

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def paper_folder(tmp_path_factory):
    root = tmp_path_factory.mktemp("paper")
    build_library(root)
    shutil.copy(FIXTURES / "dakd_zh.docx", root / "paper_dakd.docx")
    (root / "投稿修改说明.docx").write_bytes(b"side document")
    (root / "~$paper_dakd.docx").write_bytes(b"word lock file")
    return root


def test_resolve_folder(paper_folder, tmp_path):
    lay = resolve_folder(paper_folder)
    assert lay.kind == "docx"
    assert lay.paper.name == "paper_dakd.docx"
    assert lay.library.name == "ref"
    assert [p.name for p in lay.candidates] == ["投稿修改说明.docx"]
    tex = tmp_path / "tex"
    (tex / "figs").mkdir(parents=True)
    (tex / "main.tex").write_text("\\documentclass{article}")
    (tex / "figs" / "a.pdf").write_bytes(b"%PDF")
    assert resolve_folder(tex).kind == "tex"
    assert resolve_folder(tex).library is None  # figures are not a library


def test_evidence_ignores_pdf_glyph_spacing():
    assert locate_evidence("本文提出对抗训练方法", "大语言模型 。 本 文提出 对抗训练 方法，在") is not None
    assert locate_evidence("not here", "大语言模型") is None


def test_local_source_and_page(paper_folder):
    pdfs = scan_folder(paper_folder / "ref", Cache(paper_folder / "c.sqlite"))
    p = next(x for x in pdfs if "曾子明" in x.doc.filename)
    src = local_source(p, "对抗训练方法降低了幻觉率")
    assert src.kind == "fulltext" and "对抗训练方法" in src.excerpt
    assert "网络首发" not in src.excerpt
    assert page_of(p, "本文提出对抗训练方法") == 2  # page 1 is the CNKI cover
    scan = next(x for x in pdfs if x.doc.filename == "scan.pdf")
    assert local_source(scan, "x").kind == "none"


def test_apply_local(paper_folder):
    pdfs = scan_folder(paper_folder / "ref", Cache(paper_folder / "c.sqlite"))
    p = next(x for x in pdfs if "曾子明" in x.doc.filename)
    ref = Reference(id="r3", raw="…", title="面向古典文学问答领域的大语言模型对抗幻觉优化方法研究",
                    authors=["曾子明", "徐康"], year=2026, lang="zh", paragraph_id="p1")
    online = RefCheck(ref_id="r3", status="unverifiable", issues=["未检索到相符记录"])
    check, finding = apply_local(ref, online, p, 40)
    assert check.status == "verified" and finding is None
    assert check.matched["verified_by"] == "local_pdf"
    assert check.matched["local_file"] == p.doc.filename
    wrong = ref.model_copy(update={"authors": ["张三"], "year": 2019})
    check, finding = apply_local(wrong, online, p, 40)
    assert check.status == "mismatch"
    assert any("首作者为 曾子明" in i for i in check.issues)
    assert any("年份为 2026" in i for i in check.issues)
    assert finding.title == "文献信息与本地原文不一致"


@pytest.mark.asyncio
async def test_pipeline_with_library(paper_folder, tmp_path, monkeypatch):
    from citecheck.pipeline import run_pipeline

    _patch_llm(monkeypatch, {
        "judge": {"label": "supported", "evidence": "本文提出对抗训练方法",
                  "rationale": "原文提出了该方法"},
    })
    retrieval = _client(_empty_transport(), tmp_path)
    events: list[dict] = []
    report = await run_pipeline(
        paper_folder / "paper_dakd.docx", emit=events.append, retrieval=retrieval,
        cache=Cache(tmp_path / "c.sqlite"), library_dir=paper_folder / "ref")
    await retrieval.close()

    lib = report.library
    assert lib is not None
    assert {x.ref_id for x in lib.links} == {"r1", "r2", "r3", "r5"}
    assert any(e["type"] == "library" and e["linked"] == 4 for e in events)
    status = {c.ref_id: c.status for c in report.ref_checks}
    # databases found nothing; the local copies confirm r1/r2/r3/r5
    assert status["r1"] == status["r2"] == status["r3"] == status["r5"] == "verified"
    assert status["r4"] != "verified"
    local = [s for s in report.support_checks if s.ref_id == "r3"]
    assert local and all(s.source_kind == "fulltext" for s in local)
    assert all(s.source_file and s.source_file.endswith("曾子明.pdf") for s in local)
    sup = [s for s in local if s.label == "supported"]
    assert sup and sup[0].source_page == 2


@pytest.mark.asyncio
async def test_pipeline_confirmed_links_override(paper_folder, tmp_path, monkeypatch):
    from citecheck.pipeline import run_pipeline
    from citecheck.schema import LibraryLink

    _patch_llm(monkeypatch)
    pdfs = scan_folder(paper_folder / "ref", Cache(tmp_path / "c.sqlite"))
    zeng = next(x for x in pdfs if "曾子明" in x.doc.filename).doc.id
    retrieval = _client(_empty_transport(), tmp_path)
    report = await run_pipeline(
        paper_folder / "paper_dakd.docx", retrieval=retrieval,
        cache=Cache(tmp_path / "c.sqlite"), library_dir=paper_folder / "ref",
        library_links=[LibraryLink(ref_id="r3", doc_id=zeng, method="user", score=100),
                       LibraryLink(ref_id="r9", doc_id=zeng, method="user", score=100)])
    await retrieval.close()
    assert [(x.ref_id, x.status) for x in report.library.links] == [("r3", "confirmed")]


def test_library_scan_endpoint(paper_folder, tmp_path, monkeypatch):
    from citecheck.config import get_settings
    from citecheck.server import TOKEN, app

    monkeypatch.setenv("CITECHECK_CACHE", str(tmp_path / "t.sqlite"))
    get_settings.cache_clear()
    try:
        c = TestClient(app)
        h = {"x-citecheck-token": TOKEN} if TOKEN else {}
        r = c.post("/library/scan", data={"path": str(paper_folder)}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["paper"].endswith("paper_dakd.docx")
        assert len(body["references"]) == 5
        assert len(body["library"]["links"]) == 4
        assert body["library"]["unsupported"] == ["old.caj"]
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "p.docx").write_bytes(b"x")
        r = c.post("/library/scan", data={"path": str(empty)}, headers=h)
        assert r.status_code == 400 and "ref 文件夹" in r.json()["detail"]
    finally:
        get_settings.cache_clear()
