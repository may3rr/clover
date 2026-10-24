"""F8: inject a fixed mix of citation defects into each eval-corpus manuscript.

For every zh_papers/<dir>/manuscript.docx this writes
zh_papers/<dir>/manuscript_injected.docx plus testset/injections/<dir>.json
describing every injection and how the evaluator should detect it.

Defect mix per paper (9 injections, seed=42, deterministic):
  fake_ref x2      fabricated-but-plausible references, each cited once
  misattr  x2      single-marker sentences whose marker is swapped to an
                   unrelated real reference (Zhang-guan-li-dai)
  wrong_year x1    publication year of one reference shifted -4 years
  uncited x1       a real, in-domain reference added but never cited
  stacking x1      a sentence citing six references at once
  typo x2          Chinese wrong-character in a citing sentence

ref_reorder is intentionally not injected: it is an export-layer feature
(labels stay bound to entries), not a detection target.

Run:  python demo/testset/inject_corpus.py
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from docx import Document

HERE = Path(__file__).resolve().parent

FAKES = {
    "liuqiao_kg": [
        ("Temporal knowledge graph reasoning with historical interaction "
         "encoding[J].Journal of Computer Science and Technology.2021,36(4).780-794."),
        ("Entity alignment between knowledge graphs with attribute-aware "
         "graph convolution[J].Journal of Computer Research and "
         "Development.2020,57(7).1-13."),
    ],
    "luohuilan_odt": [
        ("Feature pyramid refinement for small object detection in aerial "
         "images[J].IEEE Transactions on Image Processing.2020,29.8319-8330."),
        ("Context-aware region proposal network for multi-scale object "
         "detection[J].Pattern Recognition.2019,95.120-131."),
    ],
    "zhaoyangyang_tod": [
        ("Domain-aware dialogue state tracking with schema prompts[J]."
         "Computer Speech and Language.2021,65.101-120."),
        ("Multi-party task-oriented dialogue systems with dynamic belief "
         "graphs[J].Chinese Journal of Computers.2020,43(9).1-15."),
    ],
    "yinhongpeng_odt": [
        ("Scale-adaptive anchor-free detector for tiny vehicle detection[J]."
         "Acta Automatica Sinica.2020,46(7).1-14."),
        ("Attention-guided feature fusion for video object detection[J]."
         "IEEE Transactions on Circuits and Systems for Video "
         "Technology.2020,30(9).1-12."),
    ],
    "guyingjie_mrc": [
        ("Cross-lingual machine reading comprehension with aligned passage "
         "retrieval[J].ACM Transactions on Asian and Low-Resource Language "
         "Information Processing.2020,19(3).1-17."),
        ("Numerical reasoning over machine reading comprehension with "
         "program synthesis[J].Journal of Computer Science and "
         "Technology.2020,35(6).1-14."),
    ],
}

UNCITED = {
    "liuqiao_kg": "徐增林, 盛泳潘, 贺丽荣, 王雅芳. 知识图谱技术综述[J]. 电子科技大学学报, 2016, 45(4): 589-606.",
    "luohuilan_odt": "Redmon J, Divvala S, Girshick R, et al. You only look once: Unified, real-time object detection[A]. CVPR. 2016. 779-788.",
    "zhaoyangyang_tod": "Vaswani A, Shazeer N, Parmar N, et al. Attention is all you need[A]. NIPS. 2017. 5998-6008.",
    "yinhongpeng_odt": "Redmon J, Divvala S, Girshick R, et al. You only look once: Unified, real-time object detection[A]. CVPR. 2016. 779-788.",
    "guyingjie_mrc": "Liu Y, Ott M, Goyal N, et al. RoBERTa: A robustly optimized BERT pretraining approach[J]. arXiv preprint arXiv:1907.11692. 2019.",
}

TYPOS = [("部署", "布署"), ("坐标", "座标"), ("候选", "侯选"),
         ("辨识", "辩识"), ("分量", "份量"), ("背景", "背境")]

STACK_SENT = ("此外,上述工作在数据集构建、模型结构、训练策略以及评测协议等方面"
              "均存在明显差异,系统对比可参见文献[{refs}].")


def para_text(p) -> str:
    return "".join(r.text for r in p.runs)


def rewrite(p, text: str):
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    p.add_run(text)


def find_body_and_refs(doc):
    """(body_idx list, ref_idx list, ref_heading_idx) by paragraph index."""
    ref_head = None
    for i, p in enumerate(doc.paragraphs):
        if p.text.strip() == "References":
            ref_head = i
            break
    if ref_head is None:
        raise RuntimeError("References heading not found")
    body = [i for i in range(ref_head) if "[" in doc.paragraphs[i].text or
            len(doc.paragraphs[i].text) > 60]
    refs = [i for i in range(ref_head + 1, len(doc.paragraphs))
            if re.match(r"^\[\d{1,3}\]", doc.paragraphs[i].text.strip())]
    return body, refs, ref_head


def next_ref_label(ref_texts: list[str]) -> int:
    nums = [int(m.group(1)) for t in ref_texts if (m := re.match(r"^\[(\d{1,3})\]", t))]
    return max(nums) + 1 if nums else 1


def inject_paper(directory: str, seed: int = 42):
    rng = random.Random(seed)
    src = HERE / "zh_papers" / directory / "manuscript.docx"
    doc = Document(src)
    body_idx, ref_idx, ref_head = find_body_and_refs(doc)
    ref_texts = [doc.paragraphs[i].text.strip() for i in ref_idx]
    n_refs = len(ref_texts)
    spec = {"paper": directory, "source": "manuscript.docx",
            "target": "manuscript_injected.docx", "injections": []}

    modified: set[int] = set()

    def add_note(**kw):
        spec["injections"].append(kw)

    # ---- 1. fake_ref x2 --------------------------------------------------
    label = next_ref_label(ref_texts)
    fake_snips = []
    for k, fake in enumerate(FAKES[directory][:2]):
        doc.add_paragraph(f"[{label}] {fake}")
        ref_texts.append(f"[{label}] {fake}")
        host_i = rng.choice(body_idx)
        host = doc.paragraphs[host_i]
        snip = (f"近期工作也探索了该方向的可扩展性,例如基于结构化约束的建模"
                f"方法[{label}]被证明能够显著提升跨领域场景下的鲁棒性.")
        host.add_run(snip)
        modified.add(host_i)
        fake_snips.append(snip[:24])
        add_note(id=f"fake{k+1}", kind="fake_ref", label=str(label),
                 match=fake[:30], snippet=snip[:30])
        label += 1

    # ---- 2. uncited x1 ----------------------------------------------------
    unc = UNCITED[directory]
    already = any(unc[:16] in t for t in ref_texts)
    if not already:
        ulabel = next_ref_label(ref_texts)
        doc.add_paragraph(f"[{ulabel}] {unc}")
        add_note(id="uncited", kind="uncited", label=str(ulabel), match=unc[:30])

    # ---- 3. wrong_year x1 --------------------------------------------------
    year_target = None
    # prefer an English-language reference: Chinese entries often cannot be
    # verified online, which would make the injected defect undetectable
    latin = lambda s: sum(1 for c in s if c.isascii() and c.isalpha())
    for i in sorted(ref_idx, key=lambda i: -latin(doc.paragraphs[i].text)):
        t = doc.paragraphs[i].text
        m = re.search(r"(19[7-9]\d|20[01]\d)", t)
        if m:
            year_target = (i, m.group(1))
            break
    if year_target:
        i, old = year_target
        t = doc.paragraphs[i].text
        new = str(int(old) - 4)
        rewrite(doc.paragraphs[i], t.replace(old, new, 1))
        add_note(id="wrongyear", kind="wrong_year", old_year=old, new_year=new,
                 match=re.sub(r"^\[\d{1,3}\]\s*", "", t)[:30])

    # ---- 4. misattribution x2 ----------------------------------------------
    swapped = 0
    single = [i for i in body_idx if i not in modified and
              len(re.findall(r"\[\d{1,3}\]", doc.paragraphs[i].text)) == 1]
    multi = [i for i in body_idx if i not in modified and
             len(re.findall(r"\[\d{1,3}\]", doc.paragraphs[i].text)) > 1]
    cand = [(i, 1) for i in single] + [(i, 0) for i in multi]
    rng.shuffle(cand)
    used = set()
    for i, single_only in cand:
        if swapped >= 2:
            break
        t = doc.paragraphs[i].text
        matches = list(re.finditer(r"\[(\d{1,3})\]", t))
        matches = [m for m in matches if m.start() >= 25]
        if single_only and len(matches) != 1:
            continue
        if not matches:
            continue
        m = matches[0]
        n0 = int(m.group(1))
        others = [x for x in range(1, n_refs + 1)
                  if abs(x - n0) >= 8 and x not in used and x != n0]
        if not others:
            continue
        m2 = rng.choice(others)
        used.update({n0, m2})
        rewrite(doc.paragraphs[i], t.replace(f"[{n0}]", f"[{m2}]", 1))
        modified.add(i)
        swapped += 1
        add_note(id=f"misattr{swapped}", kind="misattribution",
                 snippet=re.sub(r"\s+", "", t[max(0, m.start() - 30):m.start()])[-22:],
                 cited_label=str(m2), intended_label=str(n0))

    # ---- 5. stacking x1 ------------------------------------------------------
    host_i = rng.choice([i for i in body_idx if i not in modified])
    host = doc.paragraphs[host_i]
    refs6 = sorted(rng.sample(range(1, n_refs + 1), 6))
    sent = STACK_SENT.format(refs=",".join(map(str, refs6)))
    host.add_run(sent)
    modified.add(host_i)
    add_note(id="stacking", kind="stacking", snippet=sent[:30],
             labels=[str(x) for x in refs6])

    # ---- 6. typo x2 ------------------------------------------------------------
    done = 0
    for wrong, right in [("", "")]:
        pass
    pairs = TYPOS[:]
    rng.shuffle(pairs)
    for orig, typo in pairs:
        if done >= 2:
            break
        for i in body_idx:
            if i in modified:
                continue
            t = doc.paragraphs[i].text
            if orig in t and "[" in t:
                rewrite(doc.paragraphs[i], t.replace(orig, typo, 1))
                done += 1
                add_note(id=f"typo{done}", kind="typo", wrong=typo, right=orig,
                         snippet=t[:26])
                break

    out = HERE / "zh_papers" / directory / "manuscript_injected.docx"
    doc.save(out)
    spec_dir = HERE / "injections"
    spec_dir.mkdir(exist_ok=True)
    (spec_dir / f"{directory}.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    kinds = [x["kind"] for x in spec["injections"]]
    print(f"{directory}: {len(spec['injections'])} injections {kinds}")
    return spec


if __name__ == "__main__":
    for d in ["liuqiao_kg", "luohuilan_odt", "zhaoyangyang_tod",
              "yinhongpeng_odt", "guyingjie_mrc"]:
        inject_paper(d)
