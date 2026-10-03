"""Showcase paper for the landing page and the demo video.

Takes demo/long/long_errors.docx (EMNLP-length, author-year, injected
citation defects; see demo/long/manifest.json) and adds three spelling
mistakes in body text, so the report also carries typo revisions.

  python demo/build_showcase.py        -> demo/showcase_paper.docx

Each typo is written inside a single run, so the run's formatting stays.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document

HERE = Path(__file__).resolve().parent
SRC = HERE / "long" / "long_errors.docx"
DST = HERE / "showcase_paper.docx"

# (correct word, misspelling); each lands in a different body paragraph
TYPOS = [
    ("retrieved", "retreived"),
    ("separately", "seperately"),
    ("whether", "wether"),
]


def main() -> None:
    doc = Document(SRC)
    paras = doc.paragraphs
    ref_idx = next(i for i, p in enumerate(paras)
                   if p.text.strip() == "References")
    used: set[int] = set()
    for right, wrong in TYPOS:
        pat = re.compile(rf"\b{right}\b")
        for i, p in enumerate(paras[:ref_idx]):
            if i in used or len(p.text) < 300 or p.style.name.startswith("Heading"):
                continue
            run = next((r for r in p.runs if pat.search(r.text)), None)
            if run is None:
                continue
            run.text = pat.sub(wrong, run.text, count=1)
            used.add(i)
            print(f"{right} -> {wrong}  in paragraph {i}: {p.text[:60]}...")
            break
        else:
            raise RuntimeError(f"no body run contains {right!r}")
    doc.save(DST)
    print(DST)


if __name__ == "__main__":
    main()
