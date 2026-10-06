"""LaTeX 批注版导出：批注是整行 % 注释、落在锚点所在行上方；修订进
clover-revisions.patch 且能被 git apply 到导出的项目上；原项目不动。"""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from citecheck.export.latex import PATCH_NAME, LatexExportError, export_latex
from citecheck.parse import parse_latex
from citecheck.schema import Anchor, Finding, Report, Revision

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "proj"
    shutil.copytree(FIXTURES / "latex_numeric", d)
    # a typo to fix in the \input-ed file
    (d / "method.tex").write_text(
        "\\section{Method}\n"
        "Our approach follows \\citet{lewis2020} with a twsit.\n")
    return d


def _report(parsed, findings, revisions):
    return Report(
        document=parsed.document, sections=parsed.sections,
        paragraphs=parsed.paragraphs, markers=parsed.markers,
        references=parsed.references, ref_checks=[], claims=[],
        support_checks=[], distribution=None,
        findings=findings, revisions=revisions)


def _anchor(parsed, needle):
    p = next(p for p in parsed.paragraphs if needle in p.text)
    k = p.text.index(needle)
    return Anchor(paragraph_id=p.id, start=k, end=k + len(needle))


def test_export_comments_and_patch(project, tmp_path):
    parsed = parse_latex(project)
    lewis = next(r for r in parsed.references if r.key == "lewis2020")
    findings = [
        Finding(id="f1", layer="support", severity="high",
                anchor=_anchor(parsed, "Transformer models"),
                title="论断缺少支撑", detail="依据：被引文献未提及。\n建议：补充证据。"),
        Finding(id="f2", layer="authenticity", severity="medium",
                anchor=Anchor(paragraph_id=lewis.paragraph_id, start=0, end=5),
                title="年份不一致", detail="文中写 2020，数据库记录为 2021 @ Crossref"),
        Finding(id="f3", layer="distribution", severity="low", anchor=None,
                title="引用集中在引言", detail="其余章节引用偏少。"),
    ]
    revs = [Revision(id="v1", kind="typo", anchor=_anchor(parsed, "twsit"),
                     old="twsit", new="twist", reason="拼写错误")]
    before = {p.name: p.read_bytes() for p in project.iterdir()}
    out = export_latex(project, _report(parsed, findings, revs),
                       tmp_path / "out.zip", author="Jackie")
    # original untouched
    assert {p.name: p.read_bytes() for p in project.iterdir()} == before

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        main = zf.read("main.tex").decode()
        method = zf.read("method.tex").decode()
        bib = zf.read("refs.bib").decode()
        patch = zf.read(PATCH_NAME).decode()
    assert {"main.tex", "method.tex", "refs.bib", PATCH_NAME} <= names

    lines = main.splitlines()
    i = lines.index("Transformer models \\citep{vaswani2017} changed NLP. BERT")
    assert lines[i - 3] == "% Jackie 批注（论断支持度，高）：论断缺少支撑"
    assert lines[i - 1] == "% 建议：补充证据。"
    # unanchored finding goes to the top of the main file
    assert lines[0].startswith("% Jackie 体检")
    assert "% 其余章节引用偏少。" in lines[:6]
    # .bib comment sits right above the entry and has no bare @
    blines = bib.splitlines()
    j = next(k for k, ln in enumerate(blines) if ln.startswith("@") and "lewis2020" in ln)
    assert blines[j - 1].endswith("＠ Crossref")
    assert "twsit" in method  # the typo itself is NOT silently fixed
    assert "-Our approach follows \\citet{lewis2020} with a twsit." in patch
    assert "+Our approach follows \\citet{lewis2020} with a twist." in patch

    # the patch applies cleanly to the exported tree
    ex = tmp_path / "ex"
    with zipfile.ZipFile(out) as zf:
        zf.extractall(ex)
    if shutil.which("git"):
        r = subprocess.run(["git", "apply", "--check", PATCH_NAME],
                           cwd=ex, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    # annotated sources still parse to the same text (comments are inert)
    again = parse_latex(ex)
    assert [p.text for p in again.paragraphs] == \
        [p.text for p in parsed.paragraphs]


def test_export_refuses_when_source_changed(project, tmp_path):
    parsed = parse_latex(project)
    rep = _report(parsed, [], [])
    (project / "method.tex").write_text("\\section{Method}\nRewritten.\n")
    with pytest.raises(LatexExportError):
        export_latex(project, rep, tmp_path / "o.zip")
