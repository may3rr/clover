"""Synthetic reference folder for library tests (built into tmp_path, no
binaries in the repo). Mirrors what a Chinese author actually has: CNKI
online-first downloads with a cover page, formally published CNKI pages
with 「引用本文」, an English paper with a DOI, uncited papers from the
target journal, a byte-identical " (1)" copy, a scan and a CAJ file.

Its reference entries match tests/fixtures/dakd_zh.docx:
r1 王静静 (formal CNKI), r2 Ji et al. (English, DOI), r3 曾子明 (CNKI
cover), r4 Qwen3 (no PDF), r5 韩明星 (CNKI cover, file renamed).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

BODY_ZH = (
    "大语言模型在问答任务中会产生幻觉，即生成与事实不符的内容。"
    "本文提出对抗训练方法，在古典文学问答数据集上将幻觉率降低了12个百分点。"
    "实验表明检索增强能够提供可追溯的证据。"
)
BODY_EN = (
    "Natural language generation models often produce hallucinated text that "
    "is unfaithful to the source. We survey metrics and mitigation methods "
    "across summarization, dialogue and question answering."
)


def _canvas(path: Path):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return canvas.Canvas(str(path))


def _lines(c, lines, size=11, y=800, font="STSong-Light"):
    c.setFont(font, size)
    for ln in lines:
        c.drawString(40, y, ln)
        y -= size + 6
    return y


def _wrap(text: str, n: int = 38) -> list[str]:
    return [text[i:i + n] for i in range(0, len(text), n)]


def cnki_cover(path: Path, title: str, authors: str, venue: str, date: str,
               body: str = BODY_ZH):
    c = _canvas(path)
    _lines(c, [venue, "ISSN 2096-3467,CN 10-1478/G2", f"《{venue}》网络首发论文",
               f"题目： {title}", f"作者： {authors}", f"网络首发日期： {date}",
               f"引用格式： {authors}．{title}[J/OL]．{venue}."])
    c.showPage()
    y = _lines(c, [title, authors.replace("，", " ")], size=14)
    _lines(c, ["摘要：", *_wrap(body * 3)], y=y - 20)
    c.showPage()
    _lines(c, ["1 引言", *_wrap(body * 4)])
    c.save()


def cnki_formal(path: Path, title: str, authors: list[str], venue: str,
                year: int, body: str = BODY_ZH):
    c = _canvas(path)
    y = _lines(c, [f"总第 111 期 {year} 年 第 3 期", "研究论文"], size=9)
    y = _lines(c, [title], size=18, y=y - 10)
    y = _lines(c, ["  ".join(authors)], size=11, y=y - 6)
    cite = f"引用本文：{'，'.join(authors[:3])}，等．{title}［J］．{venue}，{year}，49（6）：41-50．(Wang Jingjing, Ye Ying. A Probe[J]. Journal, {year}.)"
    _lines(c, ["摘要：", *_wrap(body * 2), *_wrap(cite)], y=y - 10)
    c.showPage()
    _lines(c, _wrap(body * 4))
    c.save()


def english(path: Path, title: str, authors: str, doi: str | None,
            body: str = BODY_EN):
    c = _canvas(path)
    y = _lines(c, [title], size=20, font="Helvetica-Bold")
    y = _lines(c, [authors], size=11, y=y - 8, font="Helvetica")
    lines = [body[i:i + 90] for i in range(0, len(body * 3), 90)]
    if doi:
        lines.append(f"DOI: {doi}")
    _lines(c, lines, size=10, y=y - 10, font="Helvetica")
    c.showPage()
    _lines(c, [body[i:i + 90] for i in range(0, len(body * 4), 90)],
           size=10, font="Helvetica")
    c.save()


def scanned(path: Path):
    c = _canvas(path)
    c.rect(40, 400, 500, 300, fill=1)
    c.save()


def build_library(root: Path) -> Path:
    pytest.importorskip("reportlab")
    ref = root / "ref"
    ref.mkdir(parents=True)
    venue = "数据分析与知识发现"
    cnki_formal(ref / "生成式AI及其GPT类技术应用对信息管理与传播的变革探析_王静静.pdf",
                "生成式AI及其GPT类技术应用对信息管理与传播的变革探析",
                ["王静静", "叶鹰"], "中国图书馆学报", 2023)
    english(ref / "Ji et al. - 2023 - Survey of Hallucination.pdf",
            "Survey of Hallucination in Natural Language Generation",
            "Ziwei Ji, Nayeon Lee, Rita Frieske", "10.1145/3571730")
    cnki_cover(ref / "面向古典文学问答领域的大语言模型对抗幻觉优化方法研究_曾子明.pdf",
               "面向古典文学问答领域的大语言模型对抗幻觉优化方法研究",
               "曾子明，徐康", venue, "2026-09-24")
    # renamed by the user: only the content identifies it
    cnki_cover(ref / "fact-check.pdf", "融合蕴含树和LLM的事实核查研究",
               "韩明星，高宏宇，许莉薇，李佳轩", venue, "2026-04-01")
    # uncited papers from the target journal (exemplars) + a distractor
    for i, (t, a) in enumerate([
        ("基于多提示学习的方面级情感分析研究", "钱玲飞，董嘉嘉"),
        ("基于分布式认知的多智能体虚假新闻检测研究", "邹逢源，任明"),
        ("基于大语言模型的命名实体识别研究现状", "阮光册，范文妍"),
    ]):
        cnki_cover(ref / f"{t}_{a.split('，')[0]}.pdf", t, a, venue, f"2026-0{i + 1}-10")
    shutil.copy(ref / "基于多提示学习的方面级情感分析研究_钱玲飞.pdf",
                ref / "基于多提示学习的方面级情感分析研究_钱玲飞 (1).pdf")
    english(ref / "siren.pdf",
            "Siren's Song in the AI Ocean: A Survey on Hallucination in Large Language Models",
            "Yue Zhang, Yafu Li", None)
    scanned(ref / "scan.pdf")
    (ref / "old.caj").write_bytes(b"CAJ")
    return ref


def cnki_article(path: Path, title: str, authors: str, venue: str, date: str,
                 n_refs: int, recent: int):
    """A full online-first article: cover, structured abstract, numbered
    sections with citation markers, a reference list (``recent`` of the
    ``n_refs`` entries from 2025-2026, the rest from 2015)."""
    c = _canvas(path)
    _lines(c, [f"《{venue}》网络首发论文", f"题目： {title}", f"作者： {authors}",
               f"网络首发日期： {date}"])
    c.showPage()
    y = _lines(c, [title, "摘要：[目的]比较方法。[方法]设计实验。[结果]效果更好。[结论]可以推广。",
                   "关键词：大语言模型"], size=11)
    body = [
        "1 引言", "大语言模型发展迅速[1]。已有研究提出多种方法[2,3]。",
        "2 相关研究", "检索增强方法被广泛采用[4-6]。知识图谱方法也有进展[7]。",
        "多智能体方法近年兴起[8]。", "3 研究方法", "本文设计了新的框架，见图1和表1。",
        "4 实验", "实验采用公开数据集[9]，结果见表2。", "5 结论", "本文方法有效。",
    ]
    _lines(c, body, y=y - 20)
    c.showPage()
    refs = ["参考文献："]
    for i in range(1, n_refs + 1):
        year = 2026 if i <= recent else 2015
        refs.append(f"[{i}] 作者{i}. 文献题名{i}[J]. 情报学报, {year}, 1(2): 3-4.")
    _lines(c, refs, size=9)
    c.save()
