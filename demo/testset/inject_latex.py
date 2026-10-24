"""F8: inject the corpus defect mix into the five English arXiv LaTeX sources.

For every raw/<arxiv>.tar.gz this writes en_papers/<name>/manuscript_injected.zip
plus injections/en_<name>.json, with the same defect kinds as the Chinese
corpus (inject_corpus.py), seed=42, deterministic:

  fake_ref x2      fabricated entries (in the paper's own .bbl / .bib
                   format), each cited once in an appended sentence
  misattr  x2      a single-key \\cite in a claim the CLEAN run extracted,
                   swapped to an unrelated entry whose text the clean run
                   retrieved
  wrong_year x1    year of one online-verified entry shifted -4 (the .bib
                   year field, or the only year in a .bbl item)
  uncited x1       a real entry never cited — .bbl projects only: BibTeX
                   drops uncited .bib entries, so there it is no defect
  stacking x1      an appended sentence citing six entries at once
  typo x2          English misspelling of a prose word in a claim paragraph

Edits go to the exact source offsets the parser maps the clean report's
text to (LatexMap.locate), so the injected project differs from the clean
one only at the injection points. Requires reports/en_<name>_clean.json.

Run:  python demo/testset/inject_latex.py
"""

from __future__ import annotations

import json
import random
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))

from citecheck.parse import parse_document  # noqa: E402

PAPERS = {"resnet": "1512.03385", "t5": "1910.10683", "gpt3": "2005.14165",
          "ddpm": "2006.11239", "vit": "2010.11929"}

# (key, authors, title, venue, year) — plausible, nonexistent
FAKES = {
    "resnet": [
        ("Lin2015pyramid", "T.~Lin and S.~Zhou", "Cascaded residual pyramids for "
         "fine-grained recognition", "In {\\em ICCV}", 2015),
        ("Park2014deepgate", "J.~Park and H.~Kim", "Gated deep supervision for "
         "very deep convolutional networks", "{\\em TPAMI}", 2014),
    ],
    "t5": [
        ("liu2019crosstask", "Liu, Wei and Zhang, Qian", "Cross-task span corruption "
         "for unified text-to-text pre-training", "Transactions of the Association "
         "for Computational Linguistics", 2019),
        ("kim2018multigran", "Kim, Seonho and Park, Jiwoo", "Multi-granularity denoising "
         "objectives for sequence-to-sequence language models",
         "Computational Linguistics", 2018),
    ],
    "gpt3": [
        ("zhao2019incontext", "Wei Zhao and Rui Lin", "In-context task induction "
         "with autoregressive language models", "{\\em Transactions of the "
         "Association for Computational Linguistics}", 2019),
        ("moran2018scaling", "Daniel Moran and Lisa Chen", "Scaling behavior of "
         "conditional language models under data repetition",
         "{\\em Journal of Machine Learning Research}", 2018),
    ],
    "ddpm": [
        ("hsu2019annealed", "Hsu, Chen and Wang, Lei", "Annealed denoising flows for "
         "high-fidelity image synthesis", "IEEE Transactions on Pattern Analysis "
         "and Machine Intelligence", 2019),
        ("ortega2018score", "Ortega, Maria and Silva, Pedro", "Score-guided Markov "
         "chains for likelihood-based generative modeling",
         "Journal of Machine Learning Research", 2018),
    ],
    "vit": [
        ("chen2019patchattn", "Chen, Yu and Huang, Min", "Patch-level self-attention "
         "for large-scale image recognition", "International Journal of Computer "
         "Vision", 2019),
        ("rossi2020globaltok", "Rossi, Marco and Weber, Anna", "Global token mixing "
         "for convolution-free visual backbones", "Pattern Recognition", 2020),
    ],
}

# real, in-domain, absent from the paper's list (.bbl projects only)
UNCITED = {
    "resnet": ("Szegedy2016inception", "C.~Szegedy, V.~Vanhoucke, S.~Ioffe, "
               "J.~Shlens, and Z.~Wojna", "Rethinking the inception architecture "
               "for computer vision", "In {\\em CVPR}", 2016),
    "gpt3": ("clark2020electra", "Kevin Clark, Minh-Thang Luong, Quoc~V. Le, and "
             "Christopher~D. Manning", "{ELECTRA}: Pre-training text encoders as "
             "discriminators rather than generators",
             "In {\\em International Conference on Learning Representations}", 2020),
}

TYPOS = [("performance", "perfomance"), ("achieve", "acheive"),
         ("separate", "seperate"), ("necessary", "neccessary"),
         ("previous", "previuos"), ("independent", "independant"),
         ("successful", "succesful"), ("receive", "recieve"),
         ("existing", "exisiting"), ("different", "diffrent"),
         ("between", "betwen"), ("their", "thier"), ("which", "wich"),
         ("training", "trainig"), ("results", "resutls")]

FAKE_SENTS = [
    " Recent work has also explored the scalability of this direction, showing "
    "that structured-constraint modeling improves robustness across domains~\\cite{%s}.",
    " Another line of research revisits this pipeline from the data-augmentation "
    "angle and reports stable gains in low-resource settings~\\cite{%s}.",
]
# one clause, like the Chinese sentence: the claim splitter cuts at ";", and
# the cited half would then sit in a different sentence from the snippet
STACK_SENT = (" Moreover, these works differ widely in data construction, model "
              "design, training strategy and evaluation protocol, and a systematic "
              "comparison is given in \\cite{%s}.")


def squash(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", (s or "").lower())


class Project:
    """Clean source files plus offset-stable edits: every edit is recorded
    against ORIGINAL offsets and applied back to front at save time."""

    def __init__(self, arxiv: str):
        self.parsed = parse_document(HERE / "raw" / f"{arxiv}.tar.gz")
        self.lmap = self.parsed.latex
        self.root = Path(self.lmap.root)
        self.files = {p.relative_to(self.root).as_posix(): p.read_bytes()
                      for p in self.root.rglob("*") if p.is_file()}
        self.edits: dict[str, list[tuple[int, int, str]]] = {}

    def text(self, rel: str) -> str:
        return self.files[rel].decode("utf-8", errors="surrogateescape")

    def edit(self, rel: str, a: int, b: int, new: str):
        for x, y, _ in self.edits.get(rel, []):
            if a < y and x < b or (a == b == x):
                raise RuntimeError(f"overlapping edit in {rel} at {a}")
        self.edits.setdefault(rel, []).append((a, b, new))

    def exact(self, pid: str, s: int, e: int):
        """(file, fs, fe) when every char of [s, e) maps verbatim."""
        first = self.lmap.locate(pid, s)
        last = self.lmap.locate(pid, e - 1)
        if not (first and last and first[2] and last[2] and first[0] == last[0]
                and last[1] - first[1] == e - 1 - s):
            return None
        return first[0], first[1], last[1] + 1

    def save(self, out: Path):
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, blob in sorted(self.files.items()):
                if rel in self.edits:
                    t = self.text(rel)
                    for a, b, new in sorted(self.edits[rel], reverse=True):
                        t = t[:a] + new + t[b:]
                    blob = t.encode("utf-8", errors="surrogateescape")
                z.writestr(rel, blob)


def clean_state(name: str):
    rep = json.loads((HERE / "reports" / f"en_{name}_clean.json").read_text())
    checks = {c["ref_id"]: c for c in rep["ref_checks"]}
    sourced = {sc["ref_id"] for sc in rep["support_checks"]
               if sc.get("source_kind") in {"abstract", "fulltext"}}
    claimed = {mid for c in rep["claims"] for mid in c.get("marker_ids") or []}
    refs = {}
    for r in rep["references"]:
        if not r.get("key"):
            continue
        c = checks.get(r["id"]) or {}
        refs[r["key"]] = {"verified": c.get("status") == "verified",
                          "year": r.get("year"),
                          "db_year": (c.get("matched") or {}).get("year"),
                          "sourced": r["id"] in sourced,
                          "title": r.get("title") or ""}
    return rep, refs, claimed, {c["paragraph_id"] for c in rep["claims"]}


def entry_span(text: str, pos: int, bib: bool) -> tuple[int, int]:
    """[start, end) of the .bib entry / .bbl item starting at pos."""
    if bib:
        open_ = text.index("{", pos)
        depth, i = 0, open_
        while i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            if depth == 0:
                return pos, i + 1
            i += 1
        raise RuntimeError("unbalanced bib entry")
    nxt = [k for k in (text.find("\\bibitem", pos + 8),
                       text.find("\\end{thebibliography}", pos)) if k >= 0]
    return pos, min(nxt)


def cite_arg_span(text: str, pos: int) -> tuple[int, int] | None:
    """[start, end) of the {keys} argument of the cite command at pos."""
    m = re.match(r"\\[A-Za-z]*cite[A-Za-z]*\*?", text[pos:])
    if not m:
        return None
    i = pos + m.end()
    while True:  # optional [..] arguments
        while i < len(text) and text[i] in " \t\n~":
            i += 1
        if i < len(text) and text[i] == "[":
            i = text.index("]", i) + 1
            continue
        break
    if i >= len(text) or text[i] != "{":
        return None
    return i + 1, text.index("}", i)


def inject(name: str, seed: int = 42):
    rng = random.Random(seed)
    P = Project(PAPERS[name])
    parsed = P.parsed
    rep, clean_refs, claimed, prose = clean_state(name)
    paras = {p.id: p for p in parsed.paragraphs}
    ref_by_key = {r.key: r for r in parsed.references if r.key}
    order = [r.key for r in parsed.references if r.key]
    spec = {"paper": f"en_{name}", "source": f"raw/{PAPERS[name]}.tar.gz",
            "target": f"en_papers/{name}/manuscript_injected.zip",
            "injections": []}
    used_pids: set[str] = set()

    # the bibliography file and where new entries go
    r0 = parsed.references[0]
    bib_rel, _, _ = P.lmap.locate(r0.paragraph_id, 0)
    is_bib = bib_rel.endswith(".bib")
    bib_text = P.text(bib_rel)
    if is_bib:
        new_at = len(bib_text)
    else:
        new_at = bib_text.index("\\end{thebibliography}")
    alpha = (not is_bib) and re.search(r"\\bibitem\[", bib_text) is not None

    def new_entry(key, authors, title, venue, year):
        if is_bib:
            return (f"\n@article{{{key},\n  title={{{title}}},\n  author={{{authors}}},\n"
                    f"  journal={{{venue}}},\n  year={{{year}}}\n}}\n")
        lab = ""
        if alpha:
            sur = re.sub(r"[^A-Za-z]", "", authors.split(",")[0].split()[-1])
            lab = f"[{sur[:3]}{str(year)[2:]}]"
        return (f"\\bibitem{lab}{{{key}}}\n{authors}.\n\\newblock {title}.\n"
                f"\\newblock {venue}, {year}.\n\n")

    # host paragraphs: prose that produced claims, ending in a sentence
    # stop whose source char is verbatim (so text appended after it lands
    # inside the same paragraph)
    def host_end(pid):
        t = paras[pid].text.rstrip()
        if not t.endswith("."):
            return None
        loc = P.exact(pid, len(t) - 1, len(t))
        return (loc[0], loc[2]) if loc else None

    hosts = sorted(pid for pid in prose if pid in paras and host_end(pid)
                   and paras[pid].cell is None)

    def append_sentence(sent):
        pid = rng.choice([h for h in hosts if h not in used_pids])
        rel, at = host_end(pid)
        P.edit(rel, at, at, sent)
        used_pids.add(pid)
        return pid

    def rendered(sent):
        # prose part of the appended sentence, as the parser renders it
        return re.sub(r"~?\\cite\{[^}]*\}.*$", "", sent).strip()[:30]

    # ---- 1. fake_ref x2 -------------------------------------------------
    entries = ""
    for k, (key, au, ti, ve, yr) in enumerate(FAKES[name]):
        assert key not in ref_by_key
        entries += new_entry(key, au, ti, ve, yr)
        sent = FAKE_SENTS[k] % key
        append_sentence(sent)
        spec["injections"].append({"id": f"fake{k + 1}", "kind": "fake_ref",
                                   "key": key, "match": ti[:30],
                                   "snippet": rendered(sent)})

    # ---- 2. uncited (.bbl only) -------------------------------------------
    if name in UNCITED:
        key, au, ti, ve, yr = UNCITED[name]
        assert squash(ti)[:20] not in {squash(r.title or "")[:20]
                                       for r in parsed.references}
        entries += new_entry(key, au, ti, ve, yr)
        spec["injections"].append({"id": "uncited", "kind": "uncited",
                                   "key": key, "match": ti[:30]})
    P.edit(bib_rel, new_at, new_at, entries)

    # ---- 3. wrong_year ----------------------------------------------------
    cands = []
    for key in order:
        info = clean_refs.get(key)
        if not (info and info["verified"] and info["year"]
                and info["year"] == info["db_year"]):
            continue
        r = ref_by_key[key]
        rel, pos, _ = P.lmap.locate(r.paragraph_id, 0)
        t = P.text(rel)
        a, b = entry_span(t, pos, rel.endswith(".bib"))
        body = t[a:b]
        if rel.endswith(".bib"):
            ms = list(re.finditer(r"\byear\s*=\s*[{\"]?\s*((?:19|20)\d{2})", body))
        else:
            # the item header (\bibitem[label]{Key2015}) and URLs / arXiv
            # ids carry years too; only the entry text counts
            dated = re.sub(r"\\bibitem(?:\[[^\]]*\])?\{[^}]*\}|\\url\{[^}]*\}"
                           r"|https?://\S+|\d{4}\.\d{4,5}",
                           lambda m: " " * len(m.group(0)), body)
            ms = list(re.finditer(r"(?<!\d)((?:19|20)\d{2})(?!\d)", dated))
        if len(ms) == 1 and int(ms[0].group(1)) == info["year"]:
            cands.append((key, rel, a + ms[0].start(1), a + ms[0].end(1),
                          ms[0].group(1)))
    key, rel, ya, yb, old = rng.choice(cands)
    new = str(int(old) - 4)
    P.edit(rel, ya, yb, new)
    spec["injections"].append({"id": "wrongyear", "kind": "wrong_year", "key": key,
                               "old_year": old, "new_year": new,
                               "match": clean_refs[key]["title"][:30]})

    # ---- 4. misattribution x2 ---------------------------------------------
    cand = [m for m in parsed.markers
            if m.id in claimed and len(m.keys) == 1 and m.keys[0] in ref_by_key
            and m.paragraph_id in paras and m.start >= 25
            and m.paragraph_id not in used_pids]
    rng.shuffle(cand)
    swapped = 0
    taken: set[str] = set()
    for m in cand:
        if swapped >= 2:
            break
        k0 = m.keys[0]
        if k0 in taken or m.paragraph_id in used_pids:
            continue
        loc = P.lmap.locate(m.paragraph_id, m.start)
        if not loc:
            continue
        rel, pos, _ = loc
        arg = cite_arg_span(P.text(rel), pos)
        if not arg or P.text(rel)[arg[0]:arg[1]].strip() != k0:
            continue
        i0 = order.index(k0)
        others = [k for j, k in enumerate(order)
                  if abs(j - i0) >= 8 and k not in taken
                  and clean_refs.get(k, {}).get("sourced")]
        if not others:
            continue
        k2 = rng.choice(others)
        P.edit(rel, arg[0], arg[1], k2)
        taken.update({k0, k2})
        used_pids.add(m.paragraph_id)
        swapped += 1
        ptext = paras[m.paragraph_id].text
        spec["injections"].append({
            "id": f"misattr{swapped}", "kind": "misattribution",
            "snippet": re.sub(r"\s+", "", ptext[max(0, m.start - 30):m.start])[-22:],
            "cited_key": k2, "intended_key": k0})

    # ---- 5. stacking ---------------------------------------------------------
    six = sorted(rng.sample(order, 6), key=order.index)
    sent = STACK_SENT % ",".join(six)
    append_sentence(sent)
    spec["injections"].append({"id": "stacking", "kind": "stacking",
                               "snippet": rendered(sent), "keys": six})

    # ---- 6. typo x2 ------------------------------------------------------------
    pairs = TYPOS[:]
    rng.shuffle(pairs)
    done = 0
    marker_spans: dict[str, list[tuple[int, int]]] = {}
    for m in parsed.markers:
        marker_spans.setdefault(m.paragraph_id, []).append((m.start, m.end))
    for orig, typo in pairs:
        if done >= 2:
            break
        for pid in sorted(prose):
            if pid in used_pids or pid not in paras or paras[pid].cell is not None:
                continue
            t = paras[pid].text
            hit = None
            for o in re.finditer(rf"\b{orig}\b", t):
                if any(o.start() < e and s < o.end() for s, e in marker_spans.get(pid, [])):
                    continue
                loc = P.exact(pid, o.start(), o.end())
                if loc and P.text(loc[0])[loc[1]:loc[2]] == orig:
                    hit = (o, loc)
                    break
            if not hit:
                continue
            o, (rel, fa, fb) = hit
            P.edit(rel, fa, fb, typo)
            used_pids.add(pid)
            done += 1
            fixed = t[:o.start()] + typo + t[o.end():]
            spec["injections"].append({
                "id": f"typo{done}", "kind": "typo", "wrong": typo, "right": orig,
                "snippet": fixed[max(0, o.start() - 20):o.start() + len(typo) + 6]})
            break

    out = HERE / "en_papers" / name / "manuscript_injected.zip"
    P.save(out)
    (HERE / "injections" / f"en_{name}.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"en_{name}: {len(spec['injections'])} injections "
          f"{[x['kind'] for x in spec['injections']]}")
    return spec


if __name__ == "__main__":
    for n in (sys.argv[1:] or PAPERS):
        inject(n)
