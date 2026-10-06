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
