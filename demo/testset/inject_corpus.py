"""F8: inject a fixed mix of citation defects into each eval-corpus manuscript.

For every zh_papers/<dir>/manuscript.docx this writes
zh_papers/<dir>/manuscript_injected.docx plus testset/injections/<dir>.json
describing every injection and how the evaluator should detect it.

Defect mix per paper (9 injections, seed=42, deterministic):
  fake_ref x2      fabricated-but-plausible references, each cited once
  misattr  x2      citation markers swapped to an unrelated real reference
                   (Zhang-guan-li-dai) — only markers the CLEAN run's claims
                   actually cite, never author superscripts / table numbers;
                   the swapped-in reference exists as an entry and the clean
                   run retrieved its text (abstract or full text)
  wrong_year x1    publication year of one online-verified reference shifted
                   -4 years; only entries whose text holds exactly one
                   year-looking number and the clean run read that same
                   year, so the edit is the publication year and nothing else
  uncited x1       a real, in-domain reference added but never cited
  stacking x1      a sentence citing six references at once
  typo x2          Chinese wrong-character in a citing sentence (post-
                   replacement snippet recorded, never inside a marker)

Placement uses the CLEAN-run report as a whitelist (paragraphs that produced
claims / markers those claims cite / refs verified online / refs whose text
was retrieved), so every
injection is detectable in principle: the corpus measures detection
capability, not parser blind spots. Requires reports/<paper>_clean.json.

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
    # 各刊按其参考文献表的原生著录样式伪造，避免样式启发式直接归类为无发表信息
    "liuqiao_kg": [  # 计算机研究与发展: 作者.题名[J].期刊,年,卷(期):页.
        ("Wang X, Li J, Zhou Y. Temporal knowledge graph reasoning with "
         "historical interaction encoding[J]. Journal of Computer Science "
         "and Technology, 2021, 36(4): 780-794."),
        ("Chen R, Xu H. Entity alignment between knowledge graphs with "
         "attribute-aware graph convolution[J]. Journal of Computer Research "
         "and Development, 2020, 57(7): 1441-1453."),
    ],
    "luohuilan_odt": [  # 电子学报: 作者.题名[J].期刊.年,(期).页
        ("Liu S, Deng Z. Feature pyramid refinement for small object "
         "detection in aerial images[J]. IEEE Transactions on Image "
         "Processing.2020,(9).8319-8330."),
        ("Zhao K, Rao Y. Context-aware region proposal network for "
         "multi-scale object detection[J]. Pattern "
         "Recognition.2019,(12).120-131."),
    ],
    "zhaoyangyang_tod": [  # 计算机学报: 作者.题名[J].期刊,年,卷(期):页
        ("Zhang M, Lei T. Domain-aware dialogue state tracking with schema "
         "prompts[J]. Computer Speech and Language, 2021, 65: 101-120."),
        ("Wang P, Yang Z. Multi-party task-oriented dialogue systems with "
         "dynamic belief graphs[J]. Chinese Journal of Computers, 2020, "
         "43(9): 1712-1727."),
    ],
    "yinhongpeng_odt": [  # 自动化学报(英文著录): Author. Title[J]. Journal, 年, 卷(期): 页
        ("Gao X, Wen L. Scale-adaptive anchor-free detector for tiny "
         "vehicle detection. Acta Automatica Sinica, 2020, 46(7): 1-14"),
        ("Chen B, Yin H. Attention-guided feature fusion for video object "
         "detection[J]. IEEE Transactions on Circuits and Systems for Video "
         "Technology, 2020, 30(9): 2211-2224."),
    ],
    "guyingjie_mrc": [  # 软件学报: Author.Title. In:Proc.., 年, 页 / [J].期刊, 年, 卷(期): 页
        ("Sun F, Liu Q. Cross-lingual machine reading comprehension with "
         "aligned passage retrieval[J].Journal of Computer Science and "
         "Technology., 2020, 35(6): 1-17."),
        ("Kim S, Park C. Numerical reasoning over machine reading "
         "comprehension with program synthesis[J].Artificial "
         "Intelligence., 2020, 285: 103-118."),
    ],
}

UNCITED = {
    "liuqiao_kg": "徐增林, 盛泳潘, 贺丽荣, 王雅芳. 知识图谱技术综述[J]. 电子科技大学学报, 2016, 45(4): 589-606.",
    "luohuilan_odt": "Redmon J, Divvala S, Girshick R, et al. You only look once: Unified, real-time object detection[A].CVPR.2016.779-788.",
    "zhaoyangyang_tod": "Zhong V, Xiong C, Socher R. Seq2SQL: Generating structured queries from natural language using reinforcement learning. 2017. https://arxiv.org/abs/1709.05178",
    "yinhongpeng_odt": "Redmon J, Divvala S, Girshick R, et al. You only look once: Unified, real-time object detection[A]. IEEE Computer Society, 2016. 779-788",
    "guyingjie_mrc": "Liu Y, Ott M, Goyal N, et al. RoBERTa: A robustly optimized BERT pretraining approach. 2019. https://arxiv.org/abs/1907.11692",
}

TYPOS = [("部署", "布署"), ("坐标", "座标"), ("候选", "侯选"),
         ("辨识", "辩识"), ("分量", "份量"), ("背景", "背境")]

FAKE_SENTS = [
    ("近期工作也探索了该方向的可扩展性,例如基于结构化约束的建模方法[{label}]"
     "被证明能够提升跨领域场景下的鲁棒性."),
    ("另有研究从数据增强的角度改进了这一流程,文献[{label}]报告了在低资源"
     "条件下的稳定收益."),
]

STACK_SENT = ("此外,上述工作在数据集构建、模型结构、训练策略以及评测协议等方面"
              "均存在明显差异,系统对比可参见文献[{refs}].")

# paragraphs a citation-marker swap must avoid: author-affiliation superscript
# lists ("尹宏鹏[1],[2]陈波"), keyword lines, table/figure captions and other
# non-prose — the parser does not treat those [n] as citations
_AFFIL = re.compile(r"\[\d{1,3}\]\s*,\s*\[\d{1,3}\]")
_FRONT = re.compile(r"关键词|Key\s*words|Keywords", re.IGNORECASE)


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def load_clean_state(directory: str):
    """Placement whitelist from the CLEAN-run report: injections land only
    where the pipeline demonstrably reads the text — paragraphs that produced
    claims, citation markers those claims cite, references verified online.
    Placed there every injection is detectable in principle, so the corpus
    measures detection capability, not parser blind spots (author-affiliation
    superscripts, running heads, table captions)."""
    rep = json.loads(
        (HERE / "reports" / f"{directory}_clean.json").read_text(encoding="utf-8"))
    pid_by_squash = {squash(p["text"]): p["id"] for p in rep["paragraphs"]}
    claimed = set()
    for c in rep["claims"]:
        claimed.update(c.get("marker_ids") or [])
    cite_markers: dict[str, list[dict]] = {}
    marker_spans: dict[str, list[tuple[int, int]]] = {}
    for m in rep["markers"]:
        if not m.get("ref_ids"):
            continue
        marker_spans.setdefault(m["paragraph_id"], []).append((m["start"], m["end"]))
        if m["id"] in claimed and re.fullmatch(r"\[\d{1,3}\]", m["raw"].strip()):
            cite_markers.setdefault(m["paragraph_id"], []).append(
                {"start": m["start"], "label": m["raw"].strip()[1:-1]})
    prose_pids = {c["paragraph_id"] for c in rep["claims"]}
    checks = {rc["ref_id"]: rc for rc in rep["ref_checks"]}
    sourced = {sc["ref_id"] for sc in rep["support_checks"]
               if sc.get("source_kind") in {"abstract", "fulltext"}}
    refs: dict[str, dict] = {}
    for r in rep["references"]:
        lm = re.match(r"^\[(\d{1,3})\]", r["raw"].strip())
        if not lm:
            continue
        rc = checks.get(r["id"]) or {}
        refs[lm.group(1)] = {
            "verified": rc.get("status") == "verified",
            "year": r.get("year"),
            "db_year": (rc.get("matched") or {}).get("year"),
            "sourced": r["id"] in sourced,
            # PDF-extraction artefacts glue back matter or a neighbour
            # entry onto a few entries; never inject into those
            "intact": len(r["raw"]) <= 400,
        }
    return pid_by_squash, cite_markers, marker_spans, prose_pids, refs


def para_text(p) -> str:
    return "".join(r.text for r in p.runs)


def splice(p, start: int, end: int, new: str):
    """Replace text[start:end] inside the runs that hold it, keeping every
    run's formatting. Rebuilding the paragraph as one plain run drops the
    superscript / style runs the parser reads, which re-splits every claim
    of the paragraph and turns its untouched sentences into new units."""
    pos = 0
    for r in p.runs:
        t = r.text
        a, b = pos, pos + len(t)
        pos = b
        if b <= start or a >= end and not (a == start == end):
            continue
        lo, hi = max(start, a) - a, min(end, b) - a
        r.text = t[:lo] + (new if a <= start else "") + t[hi:]


def find_body_and_refs(doc):
    """(body_idx list, ref_idx list, ref_heading_idx) by paragraph index."""
    ref_head = None
    for i, p in enumerate(doc.paragraphs):
        if p.text.strip() in ("References", "参考文献"):
            ref_head = i
            break
    if ref_head is None:
        raise RuntimeError("reference list heading not found")
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
    (pid_by_squash, cite_markers, marker_spans, prose_pids,
     clean_refs) = load_clean_state(directory)
    # labels the parser actually split into entries (a merged entry loses
    # its successor's label, e.g. luohuilan [16])
    known = sorted(int(x) for x in clean_refs if clean_refs[x]["intact"])
    spec = {"paper": directory, "source": "manuscript.docx",
            "target": "manuscript_injected.docx", "injections": []}

    modified: set[int] = set()

    def add_note(**kw):
        spec["injections"].append(kw)

    # ---- 1. fake_ref x2 --------------------------------------------------
    label = next_ref_label(ref_texts)
    fake_snips = []
    hosts = [i for i in body_idx
             if not _AFFIL.search(doc.paragraphs[i].text)
             and not _FRONT.search(doc.paragraphs[i].text)]
    for k, fake in enumerate(FAKES[directory][:2]):
        doc.add_paragraph(f"[{label}] {fake}")
        ref_texts.append(f"[{label}] {fake}")
        host_i = rng.choice([i for i in hosts if i not in modified])
        host = doc.paragraphs[host_i]
        # one sentence per fake: identical snippets would make the
        # evaluator locate both in the same paragraph
        snip = FAKE_SENTS[k].format(label=label)
        host.add_run(snip)
        modified.add(host_i)
        fake_snips.append(snip[:24])
        add_note(id=f"fake{k+1}", kind="fake_ref", label=str(label),
                 match=fake[:30], snippet=snip[:30])
        label += 1

    # ---- 2. uncited x1 ----------------------------------------------------
    unc = UNCITED[directory]
    # whitespace-insensitive: the paper's own copy may format authors
    # differently ("Vaswani A,Shazeer N" vs "Vaswani A, Shazeer N")
    already = any(squash(unc)[:16] in squash(t) for t in ref_texts)
    if not already:
        ulabel = next_ref_label(ref_texts)
        doc.add_paragraph(f"[{ulabel}] {unc}")
        add_note(id="uncited", kind="uncited", label=str(ulabel), match=unc[:30])

    # ---- 3. wrong_year x1 --------------------------------------------------
    year_target = None
    # only entries the CLEAN run verified online with the year it read
    # equal to the record's: a -4 shift then provably mismatches. The entry
    # must hold exactly one year-looking number outside URLs, so the edit
    # is the publication year — not an event year ("WWW 2010", "Proc. of
    # the 2014 Conf."), a title token ("VOT2014") or a grant number in
    # back matter glued onto the entry. Prefer English (most Latin) refs.
    latin = lambda s: sum(1 for c in s if c.isascii() and c.isalpha())
    for i in sorted(ref_idx, key=lambda i: -latin(doc.paragraphs[i].text)):
        t = doc.paragraphs[i].text
        lm = re.match(r"^\[(\d{1,3})\]", t.strip())
        info = clean_refs.get(lm.group(1)) if lm else None
        if not (info and info["verified"] and info["intact"] and info["year"]
                and info["year"] == info["db_year"]):
            continue
        dated = re.sub(r"https?://\S+|10\.\d{4,9}/\S+",
                       lambda m: " " * len(m.group(0)), t)
        ms = list(re.finditer(r"(?<!\d)((?:19|20)\d{2})(?!\d)", dated))
        if len(ms) == 1 and int(ms[0].group(1)) == info["year"]:
            year_target = (i, ms[0])
            break
    if year_target:
        i, ym = year_target
        t = doc.paragraphs[i].text
        old = ym.group(1)
        new = str(int(old) - 4)
        # slice at the matched position — str.replace would hit the first
        # occurrence, which need not be the one selected
        splice(doc.paragraphs[i], ym.start(), ym.end(), new)
        add_note(id="wrongyear", kind="wrong_year", old_year=old, new_year=new,
                 match=re.sub(r"^\[\d{1,3}\]\s*", "", t)[:30])

    # ---- 4. misattribution x2 ----------------------------------------------
    # swap only markers the CLEAN run's claims actually cite — never author
    # superscripts, table numbers or running heads
    swapped = 0
    cand = []
    for i in body_idx:
        pid = pid_by_squash.get(squash(para_text(doc.paragraphs[i])))
        if pid is None or i in modified:
            continue
        ms = [m for m in cite_markers.get(pid, []) if m["start"] >= 25]
        if ms:
            cand.append((i, ms))
    rng.shuffle(cand)
    used = set()
    for i, ms in cand:
        if swapped >= 2:
            break
        t = doc.paragraphs[i].text
        m = rng.choice(ms)
        n0 = int(m["label"])
        # find this marker's [n0] in the docx text near the report offset
        pos = None
        for occ in re.finditer(rf"\[{n0}\]", t):
            if abs(occ.start() - m["start"]) <= 12:
                pos = occ.start()
                break
        if pos is None:
            continue
        # the swapped-in reference must exist as an intact entry whose text
        # the clean run retrieved: without the cited paper's text no judge
        # can tell a wrong citation from a right one, and that coverage gap
        # is reported separately (support_definitive), not as a miss here
        others = [x for x in known
                  if abs(x - n0) >= 8 and x not in used
                  and clean_refs[str(x)]["sourced"]]
        if not others:
            continue
        m2 = rng.choice(others)
        used.update({n0, m2})
        splice(doc.paragraphs[i], pos, pos + len(f"[{n0}]"), f"[{m2}]")
        modified.add(i)
        swapped += 1
        add_note(id=f"misattr{swapped}", kind="misattribution",
                 snippet=re.sub(r"\s+", "", t[max(0, pos - 30):pos])[-22:],
                 cited_label=str(m2), intended_label=str(n0))

    # ---- 5. stacking x1 ------------------------------------------------------
    host_i = rng.choice([i for i in hosts if i not in modified])
    host = doc.paragraphs[host_i]
    refs6 = sorted(rng.sample(known, 6))
    sent = STACK_SENT.format(refs=",".join(map(str, refs6)))
    host.add_run(sent)
    modified.add(host_i)
    add_note(id="stacking", kind="stacking", snippet=sent[:30],
             labels=[str(x) for x in refs6])

    # ---- 6. typo x2 ------------------------------------------------------------
    # hosts are paragraphs that produced claims in the CLEAN run — real
    # prose the typo checker reads — and the word must not sit inside a
    # citation-marker span
    done = 0
    pairs = TYPOS[:]
    rng.shuffle(pairs)
    for orig, typo in pairs:
        if done >= 2:
            break
        for i in body_idx:
            if i in modified:
                continue
            pid = pid_by_squash.get(squash(para_text(doc.paragraphs[i])))
            if pid is None or pid not in prose_pids:
                continue
            t = doc.paragraphs[i].text
            if _FRONT.search(t) or _AFFIL.search(t):
                continue
            spans = marker_spans.get(pid, [])
            pos = next(
                (o.start() for o in re.finditer(re.escape(orig), t)
                 if not any(o.start() < e and s < o.end() for s, e in spans)),
                None)
            if pos is None:
                continue
            rewritten = t[:pos] + typo + t[pos + len(orig):]
            splice(doc.paragraphs[i], pos, pos + len(orig), typo)
            done += 1
            # record the POST-replacement text: the snippet must be findable
            # inside the injected document
            add_note(id=f"typo{done}", kind="typo", wrong=typo, right=orig,
                     snippet=rewritten[:26])
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
