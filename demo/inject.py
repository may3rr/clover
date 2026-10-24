"""T11b: inject exactly the 10 specified defects into the clean base paper.

demo/base_paper.docx -> demo/demo_paper.docx + demo/injections.json

  1-2  two fabricated references (plausible authors/venue/year/title),
       each inserted into the list and cited once in the body
  3    one real reference with a wrong year (off by >= 3 years)
  4-5  two misattributions: a claim that clearly belongs to paper A but
       cites a real, present, different-topic paper B
  6    one never-cited (real) reference in the list
  7    one sentence citing >= 6 references at once
  8-10 three typos in citing sentences, one next to a protected technical
       term (no revision may overlap the term's span)
  +    the reference list is shuffled afterwards; markers keep pointing
       at the same works, so the export layer can demo reorder revisions

Run:  python demo/inject.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from docx import Document

HERE = Path(__file__).resolve().parent
SRC = HERE / "base_paper.docx"
DST = HERE / "demo_paper.docx"
SPEC = HERE / "injections.json"

random.seed(7)

# ------------------------------------------------------------- content

FAKE_REFS = {
    "25": ("Wang L, Zhang H, Kowalski M, Ito Y. Prompt-conditioned "
           "evidence alignment for retrieval-augmented language models. "
           "Transactions on Machine Learning Research. 2023."),
    "26": ("Nakamura T, Fischer E, Brandt S. Citation graph rewiring for "
           "faithful text generation. Proceedings of the 46th ACM SIGIR "
           "Conference on Research and Development in Information "
           "Retrieval. 2023:1122-1134."),
}

UNCITED_REF = (
    "Wei J, Wang X, Schuurmans D, et al. Chain-of-thought prompting "
    "elicits reasoning in large language models. Advances in Neural "
    "Information Processing Systems. 2022;35:24824-24837.")

WRONG_YEAR_TARGET = ("Lewis P, Perez E, Piktus A, et al. "
                     "Retrieval-augmented generation")

# (paragraph-starts-with, text to append)
APPENDS = [
    ("Retrieval-augmented generation combines",
     " Prompt-conditioned evidence alignment has been proposed to "
     "tighten this coupling between retriever and generator [25]."),
    ("Retrieval pipelines for open-domain tasks",
     " ColBERTv2 achieves strong recal on BEIR-style benchmarks [12]."),
    ("Evaluation has developed in parallel",
     " FActScore measures factual precision by counting lexical overlap "
     "between the generation and its sources [20]."),
    ("Hallucination itself has been surveyed",
     " SelfCheckGPT flags hallucinations by fine-tuning a classifier on "
     "the model's internal gradients [21]."),
    ("Three observations stand out",
     " These themes recur across the retrieval, grounding and "
     "attribution literature [3, 6, 14, 18, 19, 21]. Citation-graph "
     "rewiring has also been explored as a way to repair attribution "
     "links after generation [26]."),
]

# (paragraph-starts-with, wrong, right)
TYPO_EDITS = [
    ("Retrieval-augmented generation combines",
     "Retrieval-augmented", "Retreival-augmented"),
    ("However, grounding is not the same",
     "received", "recieved"),
]


def _para_text(p) -> str:
    return "".join(r.text for r in p.runs)


def _rewrite(p, text: str):
    """Replace a paragraph's runs with a single run (plain body text)."""
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    p.add_run(text)


def main() -> None:
    doc = Document(SRC)

    ref_heading_idx = next(
        i for i, p in enumerate(doc.paragraphs)
        if _para_text(p).strip() == "References")
    ref_paras = list(doc.paragraphs[ref_heading_idx + 1:])
    assert len(ref_paras) == 24 and all(
        _para_text(p).lstrip().startswith("[") for p in ref_paras)

    # --- injected sentences -------------------------------------------
    changed = set()
    for prefix, addition in APPENDS:
        for p in doc.paragraphs:
            if _para_text(p).startswith(prefix):
                p.add_run(addition)
                changed.add(prefix)
                break
        else:
            raise RuntimeError(f"paragraph not found: {prefix!r}")

    # --- typos ---------------------------------------------------------
    for prefix, right, wrong in TYPO_EDITS:
        for p in doc.paragraphs:
            t = _para_text(p)
            if t.startswith(prefix):
                assert right in t, (prefix, right)
                _rewrite(p, t.replace(right, wrong, 1))
                break
        else:
            raise RuntimeError(f"paragraph not found: {prefix!r}")

    # --- wrong year on the real Lewis ref ------------------------------
    for p in ref_paras:
        t = _para_text(p)
        if WRONG_YEAR_TARGET in t:
            assert "2020;33:9459-9474" in t
            _rewrite(p, t.replace("2020;33:9459-9474", "2016;33:9459-9474"))
            break
    else:
        raise RuntimeError("Lewis ref not found")

    # --- new reference paragraphs (labels stay literal) ----------------
    new_labels = {"25": FAKE_REFS["25"], "26": FAKE_REFS["26"],
                  "27": UNCITED_REF}
    for label, raw in new_labels.items():
        ref_paras.append(doc.add_paragraph(f"[{label}] {raw}"))

    # --- shuffle the bibliography (labels unchanged -> markers keep
    # resolving to the same works; export reorders by first appearance)
    body = doc.element.body
    sect = body.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        "sectPr")
    elems = [p._p for p in ref_paras]
    for e in elems:
        body.remove(e)
    random.shuffle(elems)
    for e in elems:
        sect.addprevious(e)

    doc.save(DST)

    injections = {
        "source": "base_paper.docx",
        "target": "demo_paper.docx",
        "injections": [
            {"id": "fake1", "kind": "fake_ref",
             "match": "Prompt-conditioned evidence alignment for "
                      "retrieval-augmented language models",
             "label": "25",
             "snippet": "Prompt-conditioned evidence alignment has been "
                        "proposed to tighten this coupling"},
            {"id": "fake2", "kind": "fake_ref",
             "match": "Citation graph rewiring for faithful text "
                      "generation",
             "label": "26",
             "snippet": "Citation-graph rewiring has also been explored "
                        "as a way to repair attribution links"},
            {"id": "wrongyear", "kind": "wrong_year",
             "match": WRONG_YEAR_TARGET,
             "old_year": "2020", "new_year": "2016"},
            {"id": "misattr1", "kind": "misattribution",
             "snippet": "SelfCheckGPT flags hallucinations by "
                        "fine-tuning a classifier on the model's "
                        "internal gradients [21].",
             "cited_label": "21", "intended_label": "21"},
            {"id": "misattr2", "kind": "misattribution",
             "snippet": "FActScore measures factual precision by "
                        "counting lexical overlap between the "
                        "generation and its sources [20].",
             "cited_label": "20", "intended_label": "20"},
            {"id": "uncited", "kind": "uncited",
             "match": "Chain-of-thought prompting elicits reasoning",
             "label": "27"},
            {"id": "stacking", "kind": "stacking",
             "snippet": "These themes recur across the retrieval, "
                        "grounding and attribution literature"},
            {"id": "typo1", "kind": "typo",
             "wrong": "Retreival-augmented", "right": "Retrieval-augmented",
             "snippet": "combines this parametric memory"},
            {"id": "typo2", "kind": "typo",
             "wrong": "recieved", "right": "received",
             "snippet": "less direct measurement"},
            {"id": "typo3", "kind": "typo",
             "wrong": "recal", "right": "recall",
             "snippet": "ColBERTv2 achieves strong",
             "protected": ["ColBERTv2", "BEIR"]},
        ],
        "reorder": {"note": "bibliography shuffled; markers unchanged"},
    }
    SPEC.write_text(json.dumps(injections, ensure_ascii=False, indent=2)
                    + "\n", encoding="utf-8")
    print(f"wrote {DST}")
    print(f"wrote {SPEC}")


if __name__ == "__main__":
    main()
