"""History endpoints: /reports list/detail/delete and export from a stored
report when the original docx is gone."""

import pytest
from fastapi.testclient import TestClient

from citecheck.server import app, TOKEN, _save_report
from citecheck.schema import Document, Finding, Report


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from citecheck.config import get_settings

    monkeypatch.setenv("CITECHECK_CACHE", str(tmp_path / "t.sqlite"))
    get_settings.cache_clear()
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


H = {"Authorization": f"Bearer {TOKEN}"}


def _report(name: str) -> Report:
    return Report(
        document=Document(title=f"Paper {name}", filename=f"{name}.docx"),
        findings=[
            Finding(id="f1", layer="norms", severity="high",
                    anchor=None, title="t", detail="d"),
            Finding(id="f2", layer="norms", severity="low",
                    anchor=None, title="t", detail="d"),
        ],
    )


def test_reports_list_get_delete(client, tmp_path):
    src = tmp_path / "a.docx"
    src.write_bytes(b"not really a docx")
    _save_report("rid1", src, "arxiv_cs_cl", _report("a"))
    _save_report("rid2", src, "arxiv_cs_cl", _report("b"))

    listing = client.get("/reports", headers=H).json()
    assert [r["id"] for r in listing] == ["rid2", "rid1"]
    assert listing[0]["filename"] == "b.docx"
    assert listing[0]["n_high"] == 1
    assert "report_json" not in listing[0]

    full = client.get("/reports/rid1", headers=H)
    assert full.status_code == 200
    assert full.json()["document"]["title"] == "Paper a"
    assert client.get("/reports/nope", headers=H).status_code == 404

    assert client.delete("/reports/rid1", headers=H).json()["ok"] is True
    assert client.delete("/reports/rid1", headers=H).status_code == 404
    assert [r["id"] for r in client.get("/reports", headers=H).json()] == [
        "rid2"
    ]


def test_export_missing_source_file(client, tmp_path):
    src = tmp_path / "gone.docx"
    src.write_bytes(b"x")
    _save_report("rid9", src, "arxiv_cs_cl", _report("gone"))
    src.unlink()  # user moved/deleted the original

    r = client.post("/reports/rid9/export", headers=H)
    assert r.status_code == 400
    assert "已移动或删除" in r.json()["detail"]
    assert client.post("/reports/nope/export", headers=H).status_code == 404


def test_export_stored_latex_report_as_zip(client, tmp_path, monkeypatch):
    """A LaTeX report exports the annotated project, from history too."""
    import zipfile
    from pathlib import Path

    from citecheck.export import latex as latex_export
    from citecheck.parse import parse_document
    from citecheck.schema import Anchor

    fx = Path(__file__).parent / "fixtures" / "latex_numeric"
    src = tmp_path / "paper.zip"
    with zipfile.ZipFile(src, "w") as zf:
        for p in fx.iterdir():
            zf.write(p, f"paper/{p.name}")
    parsed = parse_document(src)
    p = next(p for p in parsed.paragraphs if "Transformer" in p.text)
    rep = Report(
        document=parsed.document, sections=parsed.sections,
        paragraphs=parsed.paragraphs, markers=parsed.markers,
        references=parsed.references,
        findings=[Finding(id="f1", layer="support", severity="high",
                          anchor=Anchor(paragraph_id=p.id, start=0, end=5),
                          title="论断缺少支撑", detail="依据：x")])
    _save_report("tex1", src, "arxiv_cs_cl", rep)
    out = tmp_path / "out.zip"
    monkeypatch.setattr(latex_export, "default_out", lambda _src: out)

    r = client.post("/reports/tex1/export", headers=H)
    assert r.status_code == 200, r.json()
    assert r.json()["path"] == str(out)
    with zipfile.ZipFile(out) as zf:
        assert "论断缺少支撑" in zf.read("paper/main.tex").decode()


def test_benchmark_stored_report_reruns_with_venue(client, tmp_path, monkeypatch):
    """A venue typed after the check re-runs the same manuscript with the
    venue and the reference folder; the new report replaces the old row."""
    import citecheck.server as srv
    from citecheck.schema import Library, LibraryLink

    src = tmp_path / "a.docx"
    src.write_bytes(b"x")
    folder = tmp_path / "ref"
    folder.mkdir()
    old = _report("a")
    old.library = Library(folder=str(folder), links=[
        LibraryLink(ref_id="r1", doc_id="d1", method="title", status="confirmed", score=99)])
    _save_report("old1", src, "arxiv_cs_cl", old)
    seen: dict = {}

    async def fake_pipeline(path, **kw):
        seen.update(kw, path=path)
        return _report("a")

    monkeypatch.setattr(srv, "run_pipeline", fake_pipeline)
    with client:
        assert client.post("/reports/old1/venue", data={"venue": " "},
                           headers=H).status_code == 400
        r = client.post("/reports/old1/venue", data={"venue": "计算机学报"},
                        headers=H)
        assert r.status_code == 200 and r.json()["edited"] is False
        job_id = r.json()["job_id"]
        # the background run finishes on the client's loop
        for _ in range(50):
            if srv.JOBS[job_id].task.done():
                break
            client.get("/health")
    assert seen["venue"] == "计算机学报" and seen["path"] == src
    assert seen["library_dir"] == str(folder)
    assert [x.ref_id for x in seen["library_links"]] == ["r1"]
    ids = [x["id"] for x in client.get("/reports", headers=H).json()]
    assert ids == [job_id]


def test_benchmark_stored_report_source_gone(client, tmp_path):
    src = tmp_path / "gone.docx"
    src.write_bytes(b"x")
    _save_report("g1", src, "arxiv_cs_cl", _report("gone"))
    src.unlink()
    r = client.post("/reports/g1/venue", data={"venue": "EMNLP"}, headers=H)
    assert r.status_code == 400 and "原稿已移动或删除" in r.json()["detail"]


def test_benchmark_stored_report_flags_edited_source(client, tmp_path, monkeypatch):
    import os
    import time

    import citecheck.server as srv

    src = tmp_path / "a.docx"
    src.write_bytes(b"x")
    _save_report("e1", src, "arxiv_cs_cl", _report("a"))
    later = time.time() + 120
    os.utime(src, (later, later))  # the author edited the manuscript since

    async def fake_pipeline(path, **kw):
        return _report("a")

    monkeypatch.setattr(srv, "run_pipeline", fake_pipeline)
    with client:
        r = client.post("/reports/e1/venue", data={"venue": "EMNLP"}, headers=H)
        assert r.status_code == 200 and r.json()["edited"] is True
        job = srv.JOBS[r.json()["job_id"]]
        for _ in range(50):
            if job.task.done():
                break
            client.get("/health")
