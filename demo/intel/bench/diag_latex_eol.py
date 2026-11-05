import sys, tempfile
from pathlib import Path

sys.path.insert(0, r"C:\clover\backend")
from citecheck.parse import parse_latex

TEX = r"""\documentclass{article}
\begin{document}
\section{Results}
Body text.
\begin{table}[t]
\caption{Main results.}
\resizebox{\linewidth}{!}{\begin{tabular*}{\linewidth}{l|cc}
\toprule
& \multicolumn{2}{c}{BLEU} \\
Model & EN-DE & EN-FR \\
\midrule
\multirow{2}{*}{Base} & 27.3\rule{0pt}{2ex} & 38.1 \\
 & & 39.2 \\[2pt]
Big \& wide & \textbf{28.4} & 41.0 \\
\bottomrule
\end{tabular*}}
\end{table}
After the table.
\end{document}
"""

for label, kwargs in (("LF (newline='')", {"newline": ""}), ("CRLF (default)", {})):
    d = Path(tempfile.mkdtemp())
    p = d / "main.tex"
    p.write_text(TEX, encoding="utf-8", **kwargs)
    raw = p.read_bytes()
    doc = parse_latex(p)
    cell = next(x for x in doc.paragraphs if x.text == "EN-FR")
    f, off, exact = doc.latex.locate(cell.id, 0)
    src = p.read_text(encoding="utf-8")
    print(label, "bytes_has_CRLF=", b"\r\n" in raw,
          "| off=", off, "| slice=", repr(src[off:off+5]), "| exact=", exact)
