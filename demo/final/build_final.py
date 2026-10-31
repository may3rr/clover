"""决赛演示稿：罗会兰《基于深度学习的目标检测研究综述》加注入错误。

选这一篇，是因为它的文献文件夹最全：69 条参考文献里 52 篇 PDF 都在 ref/，
全部自动连上，支持度判断大多拿得到原文。

    demo/testset/zh_papers/luohuilan_odt/manuscript.docx (+ ref/)
      -> demo/final/演示稿/基于深度学习的目标检测研究综述.docx
         demo/final/演示稿/ref/        （硬链接，不占额外空间，不入库）
         demo/final/injections.json   （每处注入与检出规则，check_final.py 读取）

底稿先做三件事：作者与单位换成占位（注入的错误不能挂在真实作者名下）、
摘要里被 PDF 转换打乱的括号复原、[61] 末尾粘上的「作者简介」去掉。
原文自身的问题（Bharat 等人、Hamid 等人、ConerNet 等）保留，那是真实稿件
本来就有的。

    python demo/final/build_final.py
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
from pathlib import Path

from docx import Document

HERE = Path(__file__).resolve().parent
SRC_DIR = HERE.parent / "testset" / "zh_papers" / "luohuilan_odt"
OUT_DIR = HERE / "演示稿"
DST = OUT_DIR / "基于深度学习的目标检测研究综述.docx"
SPEC = HERE / "injections.json"


# ------------------------------------------------------------ helpers

def text_of(p) -> str:
    return "".join(r.text for r in p.runs)


def replace_in(p, old: str, new: str) -> None:
    """Replace the first ``old`` inside the runs that hold it, keeping each
    run's formatting. Only the part that differs is rewritten, so
    "MS COCO[46]" -> "MS COCO[45]" touches the digit inside the superscript
    run and the marker stays superscript."""
    full = text_of(p)
    start = full.find(old)
    if start < 0:
        raise ValueError(f"not found: {old!r} in {full[:60]!r}")
    pre = 0
    while pre < min(len(old), len(new)) and old[pre] == new[pre]:
        pre += 1
    suf = 0
    while (suf < min(len(old), len(new)) - pre
           and old[len(old) - 1 - suf] == new[len(new) - 1 - suf]):
        suf += 1
    start += pre
    end = start + len(old) - pre - suf
    new = new[pre:len(new) - suf]
    if start == end:
        insert_at(p, start, [(new, False)])
        return
    pos = 0
    placed = False
    for r in p.runs:
        t = r.text
        a, b = pos, pos + len(t)
        pos = b
        if b <= start or a >= end:
            continue
        lo, hi = max(start, a) - a, min(end, b) - a
        r.text = t[:lo] + (new if not placed else "") + t[hi:]
        placed = True


def _new_run(p, text: str, is_sup: bool):
    plain = next((r for r in p.runs if not r.font.superscript), p.runs[0])
    sup = next((r for r in p.runs if r.font.superscript), None)
    tmpl = sup if is_sup and sup is not None else plain
    el = copy.deepcopy(tmpl._r)
    for t in el.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")[1:]:
        el.remove(t)
    return el, text, is_sup


def _fill(p, el, text: str, is_sup: bool) -> None:
    run = next(r for r in p.runs if r._r is el)
    run.text = text
    run.font.superscript = True if is_sup else None


def append_parts(p, parts: list[tuple[str, bool]]) -> None:
    """Append text to a paragraph; (text, True) becomes a superscript run
    formatted like the paragraph's other citation runs."""
    for text, is_sup in parts:
        el, text, is_sup = _new_run(p, text, is_sup)
        p._p.append(el)
        _fill(p, el, text, is_sup)


def insert_at(p, pos: int, parts: list[tuple[str, bool]]) -> None:
    """Insert runs at character offset ``pos``, splitting the run there."""
    acc = 0
    for r in p.runs:
        a, b = acc, acc + len(r.text)
        acc = b
        if a <= pos <= b:
            head, tail = r.text[: pos - a], r.text[pos - a:]
            r.text = head
            anchor = r._r
            for text, is_sup in parts:
                el, text, is_sup = _new_run(p, text, is_sup)
                anchor.addnext(el)
                _fill(p, el, text, is_sup)
                anchor = el
            if tail:
                tail_el = copy.deepcopy(r._r)
                anchor.addnext(tail_el)
                _fill(p, tail_el, tail, bool(r.font.superscript))
            return
    raise ValueError(f"offset {pos} out of range")


def insert_after(p, anchor_text: str, sentence: str) -> None:
    full = text_of(p)
    i = full.find(anchor_text)
    if i < 0:
        raise ValueError(f"not found: {anchor_text!r}")
    insert_at(p, i + len(anchor_text), cite(sentence))


def cite(sentence: str) -> list[tuple[str, bool]]:
    """'…方法[70]提升…' -> runs with the [n] parts superscript."""
    out: list[tuple[str, bool]] = []
    for piece in re.split(r"(\[[\d,~\-]+\])", sentence):
        if piece:
            out.append((piece, bool(re.fullmatch(r"\[[\d,~\-]+\]", piece))))
    return out


def para_with(doc, snippet: str):
    for p in doc.paragraphs:
        if snippet in text_of(p):
            return p
    raise ValueError(f"no paragraph contains {snippet!r}")


def add_ref(doc, after_label: int, entry: str) -> None:
    anchor = para_with(doc, f"[{after_label}] ")
    new = copy.deepcopy(anchor._p)
    anchor._p.addnext(new)
    p = next(q for q in doc.paragraphs if q._p is new)
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)
    p.runs[0].text = entry


# ------------------------------------------------------------ content

FAKE_EN = ("[70] WANG Zhen,CHEN Lei,ZHANG Yu,et al.Adaptive scale-aware feature "
           "aggregation for small object detection[J].IEEE Transactions on Pattern "
           "Analysis and Machine Intelligence,2019,41( 7) : 2315 -2329.")
CHIMERA = ("[71] GIRSHICK R,HE K.Iterative region proposal refinement with feedback "
           "for object detection[A].International Conference on Computer Vision[C]."
           "Italy: IEEE,2017.3021 -3029.")
DUPLICATE = ("[72] LIU W,ANGUELOV D,ERHAN D,et al.SSD: Single Shot MultiBox Detector"
             "[A].European Conference on Computer Vision[C].Netherlands: Springer,"
             "2016.21 -37.")
UNCITED = ("[73] CARION N,MASSA F,SYNNAEVE G,et al.End-to-end object detection with "
           "transformers[A].European Conference on Computer Vision[C].Switzerland: "
           "Springer,2020.213 -229.")


def build() -> list[dict]:
    doc = Document(SRC_DIR / "manuscript.docx")
    P = doc.paragraphs
    inj: list[dict] = []

    # ---- base cleanup (not injections)
    P[1].runs[0].text = "作者甲，作者乙"
    for r in P[2].runs:
        r.text = ""
    P[2].runs[0].text = "(某高校信息工程学院)"
    P[6].runs[0].text = "Author A，Author B"
    replace_in(para_with(doc, "介绍了基于区域的卷积神经网络Network"),
               "基于区域的卷积神经网络Network，R-CNN)系列算法，然后从四个维度综述了"
               "研究者( Region with Convolutional Neural在R-CNN",
               "基于区域的卷积神经网络( Region with Convolutional Neural Network，"
               "R-CNN)系列算法，然后从四个维度综述了研究者在R-CNN")
    replace_in(para_with(doc, "[61] YI J"), "作者简介", "")

    # ---- 真实性
    add_ref(doc, 69, FAKE_EN)
    outlook = para_with(doc, "一是如何有效的结合上下文信息")
    append_parts(outlook, cite("在小目标检测方面，2019年Wang等人[70]提出了尺度感知的"
                               "特征聚合方法，在小目标检测上进一步提升了精度．"))
    inj.append({"id": "fake_en", "layer": "真实性", "kind": "fake_ref", "label": "70",
                "what": "完全编造的英文文献（作者、标题、期刊卷期都像真的）",
                "snippet": "2019年Wang等人[70]提出了尺度感知的特征聚合方法"})

    add_ref(doc, 70, CHIMERA)
    append_parts(outlook, cite("在候选区域质量方面，Girshick等人[71]进一步提出了迭代式的"
                               "候选区域反馈优化方法，提升了候选区域的召回率．"))
    inj.append({"id": "chimera", "layer": "真实性", "kind": "fake_ref", "label": "71",
                "what": "真实作者配编造标题（大模型幻觉文献的典型样子）",
                "snippet": "Girshick等人[71]进一步提出了迭代式的候选区域反馈优化方法"})

    replace_in(para_with(doc, "[55] SZEGEDY C"), "2016.2818", "2012.2818")
    inj.append({"id": "wrong_year", "layer": "真实性", "kind": "wrong_year", "label": "55",
                "what": "真实文献年份写错（2016 写成 2012）", "old": "2016", "new": "2012"})

    # ---- 支持度
    p = para_with(doc, "2015 年，Girshick 等人[21]提出了Fast R-CNN")
    replace_in(p, "Girshick 等人", "He 等人")
    inj.append({"id": "author_swap", "layer": "支持度", "kind": "author_swap", "label": "21",
                "what": "正文写的作者与被引文献作者对不上（Fast R-CNN 写成 He 等人）",
                "snippet": "2015 年，He 等人[21]提出了Fast R-CNN"})

    p = para_with(doc, "借鉴了文献[63]对关键点检测的思想")
    replace_in(p, "借鉴了文献[63]", "借鉴了文献[40]")
    inj.append({"id": "misattr_topic", "layer": "支持度", "kind": "misattribution",
                "label": "40", "what": "张冠李戴：关键点检测的思想引成了 Transformer",
                "snippet": "借鉴了文献[40]对关键点检测的思想"})

    p = para_with(doc, "MS COCO[46]数据集用于目标检测、语义分割")
    replace_in(p, "MS COCO[46]", "MS COCO[45]")
    inj.append({"id": "misattr_dataset", "layer": "支持度", "kind": "misattribution",
                "label": "45", "what": "张冠李戴：介绍 MS COCO 却引了 ImageNet 的论文",
                "snippet": "MS COCO[45]数据集用于目标检测、语义分割"})

    p = para_with(doc, "数据集上的检测精度达到了58. 5%")
    replace_in(p, "58. 5%", "78. 5%")
    inj.append({"id": "number_rcnn", "layer": "支持度", "kind": "number", "label": "15",
                "what": "数字与原文不符：R-CNN 在 VOC2007 上 58.5% 写成 78.5%",
                "snippet": "检测精度达到了78. 5%"})

    p = para_with(doc, "SPP-Net的检测速率比R-CNN 快了24 ~102 倍")
    replace_in(p, "快了24 ~102 倍", "快了240 ~1020 倍")
    # 原句没有引用标记，不构成论断；补上 [20]，数字才归到这篇文献名下
    insert_after(p, "快了240 ~1020 倍", "[20]")
    inj.append({"id": "number_spp", "layer": "支持度", "kind": "number", "label": "20",
                "what": "数字放大十倍：SPP-Net 比 R-CNN 快 24–102 倍写成 240–1020 倍",
                "snippet": "快了240 ~1020 倍[20]"})

    p = para_with(doc, "对模型的漏检有了很好的改善")
    replace_in(p, "对模型的漏检有了很好的改善",
               "使模型在MS COCO数据集上的mAP提升了10个百分点")
    inj.append({"id": "overclaim", "layer": "支持度", "kind": "number", "label": "37",
                "what": "夸大效果：Soft-NMS 在 COCO 上约提升 1–2 个点，写成 10 个百分点",
                "snippet": "mAP提升了10个百分点"})

    # ---- 分布
    insert_after(para_with(doc, "并介绍了目前目标检测领域流行的数据集"),
                 "并介绍了目前目标检测领域流行的数据集．",
                 "近年来也有大量工作对上述两类方法进行了改进[24,28,36,50,54,56,59]．")
    inj.append({"id": "stacking", "layer": "分布", "kind": "stacking",
                "what": "一句话堆了 7 篇文献，没说各自的贡献",
                "snippet": "近年来也有大量工作对上述两类方法进行了改进"})

    # ---- 规范
    add_ref(doc, 71, DUPLICATE)
    append_parts(outlook, cite("此外，SSD[72]等一阶段方法在嵌入式设备上的部署也值得关注．"))
    inj.append({"id": "duplicate", "layer": "规范", "kind": "duplicate", "label": "72",
                "what": "同一篇 SSD 在列表里出现两次（[43] 与 [72]）"})

    add_ref(doc, 72, UNCITED)
    inj.append({"id": "uncited", "layer": "规范", "kind": "uncited", "label": "73",
                "what": "列表里的 DETR 正文从未引用"})

    p = para_with(doc, "所以有些研究者提出了Anchor-free的改进方法")
    append_parts(p, cite("近期也有工作尝试用Transformer结构直接预测检测框集合[74]．"))
    inj.append({"id": "dangling", "layer": "规范", "kind": "dangling", "label": "74",
                "what": "正文引了 [74]，列表里没有这一条（本想引 [73]，编号错位）",
                "snippet": "直接预测检测框集合[74]"})

    for n, (snip, right, wrong, token) in enumerate([
        ("依赖于选择性搜索算法[18]来产生候选区域", "来产生候选区域", "来产生侯选区域", "侯选"),
        ("按照分类置信度排序", "分类置信度", "分类制信度", "制信"),
        ("Feature Pyramid Network，FPN", "Pyramid Network", "Pyramid Netwrok", "Netwrok"),
    ], 1):
        replace_in(para_with(doc, snip), right, wrong)
        inj.append({"id": f"typo_{n}", "layer": "规范", "kind": "typo",
                    "what": f"错别字：{token}", "wrong": token})

    # [68] Open Images 与 [69] LVIS 在列表里互换，正文标记跟着换，指向的文献不变：
    # 正文先出现 [69] 再出现 [68]，顺序编码制要求按首次引用顺序重排
    e68, e69 = para_with(doc, "[68] KUZNETSOVA"), para_with(doc, "[69] GUPTA")
    t68, t69 = text_of(e68), text_of(e69)
    for r in e68.runs[1:]:
        r._r.getparent().remove(r._r)
    for r in e69.runs[1:]:
        r._r.getparent().remove(r._r)
    e68.runs[0].text = "[68]" + t69[len("[69]"):]
    e69.runs[0].text = "[69]" + t68[len("[68]"):]
    for snip, old, new in [("PASCAL VOC2012[67]、MS COCO[46]", "LIVS[69]", "LIVS[68]"),
                           ("PASCAL VOC2012[67]、MS COCO[46]", "Open Images[68]",
                            "Open Images[69]"),
                           ("Open Images[68]数据集是", "Open Images[68]", "Open Images[69]"),
                           ("LIVS[69]数据集是2019年", "LIVS[69]", "LIVS[68]")]:
        replace_in(para_with(doc, snip), old, new)
    inj.append({"id": "reorder", "layer": "规范", "kind": "reorder",
                "what": "列表里 [68] 与 [69] 顺序颠倒，正文先引 [69]，需要按首次引用顺序重排"})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc.save(DST)
    return inj


def link_refs() -> None:
    """ref/ as hard links of the testset PDFs: a real folder for drag-in,
    no extra disk space."""
    dst = OUT_DIR / "ref"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir()
    for f in sorted((SRC_DIR / "ref").iterdir()):
        if f.is_file():
            os.link(f, dst / f.name)


def main() -> None:
    inj = build()
    link_refs()
    SPEC.write_text(json.dumps({"target": str(DST.relative_to(HERE)), "injections": inj},
                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{DST}  {len(inj)} injections")


if __name__ == "__main__":
    main()
