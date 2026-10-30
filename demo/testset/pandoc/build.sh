#!/usr/bin/env bash
# 生成 F33 用的 pandoc docx 样本，输出到 out/（不入库）。
# 依赖：pandoc ≥ 3、~/Zotero/styles/ 下的 CSL、conda 环境 claude（画示意图）。
set -euo pipefail
cd "$(dirname "$0")"
STYLES="${CSL_DIR:-$HOME/Zotero/styles}"
RAW=../raw
mkdir -p out out/ddpm

# 示意图：纯色 PNG，只为让 docx 里有一张图
[ -f figure1.png ] || python - <<'PY'
import struct, zlib
w, h = 64, 32
raw = b"".join(b"\x00" + b"\x23\x83\xe2" * w for _ in range(h))
def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
    + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
open("figure1.png", "wb").write(png)
PY

# 1. Markdown，数字型（IEEE）
pandoc paper.md --citeproc --bibliography refs.bib --csl "$STYLES/ieee.csl" \
  -o out/md_ieee.docx
# 2. Markdown，作者年份型（APA）
pandoc paper.md --citeproc --bibliography refs.bib --csl "$STYLES/apa.csl" \
  -o out/md_apa.docx
# 3. Markdown，中文 GB/T 7714 数字型
pandoc paper_zh.md --citeproc --bibliography refs_zh.bib \
  --csl "$STYLES/china-national-standard-gb-t-7714-2015-numeric.csl" \
  -o out/md_gbt.docx
# 3b. 正文引用带超链接（link-citations），数字型与作者年份型各一份
pandoc paper.md --citeproc --bibliography refs.bib --csl "$STYLES/ieee.csl" \
  -M link-citations=true -o out/md_ieee_linked.docx
pandoc paper.md --citeproc --bibliography refs.bib --csl "$STYLES/apa.csl" \
  -M link-citations=true -o out/md_apa_linked.docx
# 4. LaTeX（DDPM 原始 arXiv 源码）转 docx，pandoc 默认 Chicago 作者年份
tar xzf "$RAW/2006.11239.tar.gz" -C out/ddpm
(cd out/ddpm && pandoc main.tex --citeproc --bibliography main.bib \
  -o ../latex_ddpm.docx)
# 5. 同一份 LaTeX，数字型（IEEE）
(cd out/ddpm && pandoc main.tex --citeproc --bibliography main.bib \
  --csl "$STYLES/ieee.csl" -o ../latex_ddpm_ieee.docx)
# 6. 同一份 LaTeX，作者年份型并带超链接，用作正文引用的标准答案
(cd out/ddpm && pandoc main.tex --citeproc --bibliography main.bib \
  -M link-citations=true -o ../latex_ddpm_linked.docx)
ls -la out/*.docx
