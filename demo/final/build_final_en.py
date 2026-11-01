"""英文决赛演示稿：ResNet（He 等 2015，arXiv 1512.03385）LaTeX 源码加注入错误。

中文演示稿走 Word，这一篇走 LaTeX：拖入压缩包，问题写成 % 注释，错别字进
clover-revisions.patch。选 ResNet 是因为它家喻户晓，50 条参考文献大多能拿到
开放获取 PDF（demo/testset/en_papers/resnet/ref/，由 item_bench/fetch_refs.py 下载）。

    demo/testset/raw/1512.03385.tar.gz (+ en_papers/resnet/ref/)
      -> demo/final/英文演示稿/deep_residual_learning.zip
         demo/final/英文演示稿/ref/          （硬链接，不入库）
         demo/final/injections_en.json        （check_final.py 读取）

底稿只做一件事：作者与单位换成占位，注入的错误不能挂在真实作者名下。
参考文献重排不适用于 LaTeX（顺序由编译决定），其余注入类型与中文演示稿一一对应。

    python demo/final/build_final_en.py
    python demo/final/check_final.py demo/final/runs/en_v1.json demo/final/injections_en.json
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTSET = HERE.parent / "testset"
SRC = TESTSET / "raw" / "1512.03385.tar.gz"
REF_SRC = TESTSET / "en_papers" / "resnet" / "ref"
OUT_DIR = HERE / "英文演示稿"
DST = OUT_DIR / "deep_residual_learning.zip"
SPEC = HERE / "injections_en.json"
TEX = "residual_v1_arxiv_release.tex"
BBL = "residual_v1_arxiv_release.bbl"


def sub(s: str, old: str, new: str) -> str:
    """Replace exactly one occurrence; fail loudly if the anchor drifts."""
    n = s.count(old)
    if n != 1:
        raise ValueError(f"expected 1 match, got {n}: {old!r}")
    return s.replace(old, new)


def bib_after(bbl: str, key: str, entry: str) -> str:
    """Insert a \\bibitem block right after the block of ``key``."""
    start = bbl.index("\\bibitem{" + key + "}")
    nxt = bbl.find("\\bibitem{", start + 1)
    if nxt < 0:
        nxt = bbl.index("\\end{thebibliography}")
    return bbl[:nxt] + entry.strip() + "\n\n" + bbl[nxt:]


FAKE = r"""
\bibitem{Wang2015scale}
Z.~Wang, L.~Chen, and Y.~Zhang.
\newblock Adaptive scale-aware residual aggregation for small object recognition.
\newblock {\em IEEE Transactions on Pattern Analysis and Machine Intelligence},
  37(9):1812--1826, 2015.
"""
CHIMERA = r"""
\bibitem{Girshick2015refine}
R.~Girshick and K.~He.
\newblock Iterative region proposal refinement with feedback for object detection.
\newblock In {\em ICCV}, 2015.
"""
DUPLICATE = r"""
\bibitem{Ren2015b}
S.~Ren, K.~He, R.~Girshick, and J.~Sun.
\newblock Faster {R-CNN}: Towards real-time object detection with region
  proposal networks.
\newblock In {\em NIPS}, 2015.
"""
UNCITED = r"""
\bibitem{Redmon2016}
J.~Redmon, S.~Divvala, R.~Girshick, and A.~Farhadi.
\newblock You only look once: Unified, real-time object detection.
\newblock In {\em CVPR}, 2016.
"""


def build(files: dict[str, bytes]) -> list[dict]:
    tex = files[TEX].decode("utf-8")
    bbl = files[BBL].decode("utf-8")
    inj: list[dict] = []

    # ---- base cleanup (not an injection): placeholder authors
    start = tex.index("\\author{")
    end = tex.index("}\n", tex.index("@microsoft.com")) + 1
    tex = tex[:start] + "\\author{Author A \\qquad Author B \\\\\n\\large Anonymous Institute}" \
        + tex[end:]

    # ---- 真实性
    bbl = bib_after(bbl, "Vedaldi2008", FAKE)
    tex = sub(tex, "Both of them are powerful shallow representations",
              "Wang et al.~\\cite{Wang2015scale} further aggregated residual vectors "
              "across scales for small object recognition. "
              "Both of them are powerful shallow representations")
    inj.append({"id": "fake_en", "layer": "真实性", "kind": "fake_ref", "key": "Wang2015scale",
                "what": "完全编造的文献（作者、标题、期刊卷期都像真的）",
                "snippet": "further aggregated residual vectors across scales"})
    bbl = bib_after(bbl, "Girshick2014", CHIMERA)
    tex = sub(tex, "Many other nontrivial visual recognition tasks",
              "Girshick and He~\\cite{Girshick2015refine} further refined region proposals "
              "with iterative feedback. Many other nontrivial visual recognition tasks")
    inj.append({"id": "chimera", "layer": "真实性", "kind": "fake_ref",
                "key": "Girshick2015refine",
                "what": "真实作者配编造标题（大模型幻觉文献的典型样子）",
                "snippet": "further refined region proposals with iterative feedback"})
    bbl = sub(bbl, "9(8):1735--1780, 1997.", "9(8):1735--1780, 1993.")
    inj.append({"id": "wrong_year", "layer": "真实性", "kind": "wrong_year",
                "key": "Hochreiter1997", "what": "真实文献年份写错（LSTM 1997 写成 1993）",
                "old": "1997", "new": "1993"})

    # ---- 支持度
    tex = sub(tex, "We adopt batch normalization (BN) \\cite{Ioffe2015} right after",
              "We adopt batch normalization (BN) by Glorot et al.~\\cite{Ioffe2015} right after")
    inj.append({"id": "author_swap", "layer": "支持度", "kind": "author_swap",
                "key": "Ioffe2015",
                "what": "正文写的作者与被引文献作者对不上（BN 写成 Glorot 等人）",
                "snippet": "batch normalization (BN) by Glorot et al."})
    tex = sub(tex, "denotes ReLU \\cite{Nair2010}", "denotes ReLU \\cite{Jegou2011}")
    inj.append({"id": "misattr_topic", "layer": "支持度", "kind": "misattribution",
                "key": "Jegou2011", "what": "张冠李戴：ReLU 引成了乘积量化的论文",
                "snippet": "denotes ReLU"})
    tex = sub(tex, "PASCAL VOC 2007 and 2012 \\cite{Everingham2010} and COCO \\cite{Lin2014}.",
              "PASCAL VOC 2007 and 2012 \\cite{Everingham2010} and COCO \\cite{Russakovsky2014}.")
    inj.append({"id": "misattr_dataset", "layer": "支持度", "kind": "misattribution",
                "key": "Russakovsky2014", "what": "张冠李戴：介绍 MS COCO 却引了 ImageNet 的论文",
                "snippet": "PASCAL VOC 2007 and 2012"})
    tex = sub(tex, "The MS COCO dataset \\cite{Lin2014} involves 80 object categories.",
              "The MS COCO dataset \\cite{Lin2014} involves 180 object categories.")
    inj.append({"id": "number_coco", "layer": "支持度", "kind": "number", "key": "Lin2014",
                "what": "数字与原文不符：MS COCO 的 80 类写成 180 类",
                "snippet": "involves 180 object categories"})
    tex = sub(tex, "We adopt \\emph{Faster R-CNN} \\cite{Ren2015} as the detection method.",
              "We adopt \\emph{Faster R-CNN} \\cite{Ren2015}, which runs at 50 frames per "
              "second on a GPU, as the detection method.")
    inj.append({"id": "overclaim", "layer": "支持度", "kind": "number", "key": "Ren2015",
                "what": "夸大效果：Faster R-CNN 原文约 5 fps，写成 50 fps",
                "snippet": "which runs at 50 frames per second on a GPU"})
    tex = sub(tex, "which ensures forward propagated signals to have non-zero variances.",
              "which ensures forward propagated signals to have non-zero variances. "
              "BN \\cite{Ioffe2015} matches the accuracy of the original model with "
              "140 times fewer training steps.")
    inj.append({"id": "number_bn", "layer": "支持度", "kind": "number", "key": "Ioffe2015",
                "what": "数字放大十倍：BN 用少 14 倍的训练步数写成少 140 倍",
                "snippet": "with 140 times fewer training steps"})

    # ---- 分布
    tex = sub(tex, "Concurrent with our work, ``highway networks''",
              "Many works have since improved deep architectures "
              "\\cite{Lin2013,Goodfellow2013,Lee2014,Romero2015,Srivastava2015,Szegedy2015,He2015}. "
              "Concurrent with our work, ``highway networks''")
    inj.append({"id": "stacking", "layer": "分布", "kind": "stacking",
                "what": "一句话堆了 7 篇文献，没说各自的贡献",
                "snippet": "Many works have since improved deep architectures"})

    # ---- 规范
    bbl = bib_after(bbl, "Ren2015a", DUPLICATE)
    tex = sub(tex, "We adopt the idea of ``Networks on Conv feature maps''",
              "Region proposals follow the RPN design of \\cite{Ren2015b}. "
              "We adopt the idea of ``Networks on Conv feature maps''")
    inj.append({"id": "duplicate", "layer": "规范", "kind": "duplicate", "key": "Ren2015b",
                "what": "同一篇 Faster R-CNN 在列表里出现两次"})
    bbl = bib_after(bbl, "Raiko2012", UNCITED)
    inj.append({"id": "uncited", "layer": "规范", "kind": "uncited", "key": "Redmon2016",
                "what": "列表里的 YOLO 正文从未引用"})
    tex = sub(tex, "the weights as in \\cite{He2015} and train all plain/residual nets from scratch.",
              "the weights as in \\cite{He2015} and train all plain/residual nets from scratch. "
              "Single-stage detectors \\cite{Redmon2015} are left for future work.")
    inj.append({"id": "dangling", "layer": "规范", "kind": "dangling",
                "what": "正文引了 \\cite{Redmon2015}，列表里没有这个键（列表里是 Redmon2016）",
                "snippet": "Single-stage detectors"})
    for n, (right, wrong) in enumerate([
        ("which hamper convergence from the beginning",
         "which hamper convergance from the beginning"),
        ("and thoroughly verified by our experiments",
         "and thoroughly verifed by our experiments"),
        ("is shown to be more effective than", "is shown to be more effecitve than"),
    ], 1):
        tex = sub(tex, right, wrong)
        token = next(w for w in wrong.split() if w not in right.split())
        inj.append({"id": f"typo_{n}", "layer": "规范", "kind": "typo",
                    "what": f"错别字：{token}", "wrong": token})

    files[TEX] = tex.encode("utf-8")
    files[BBL] = bbl.encode("utf-8")
    return inj


def main() -> None:
    files: dict[str, bytes] = {}
    with tarfile.open(SRC) as tf:
        for m in tf.getmembers():
            if m.isfile():
                files[m.name] = tf.extractfile(m).read()
    inj = build(files)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    DST.write_bytes(buf.getvalue())
    dst = OUT_DIR / "ref"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir()
    if REF_SRC.is_dir():
        for f in sorted(REF_SRC.iterdir()):
            if f.is_file():
                os.link(f, dst / f.name)
    SPEC.write_text(json.dumps({"target": str(DST.relative_to(HERE)), "injections": inj},
                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{DST}  {len(inj)} injections, {len(list(dst.iterdir()))} PDFs in ref/")


if __name__ == "__main__":
    main()
