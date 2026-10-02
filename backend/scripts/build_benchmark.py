"""T4a: build the arXiv cs.CL benchmark corpus stats.

    python scripts/build_benchmark.py [--target 150] [--pool 1000]

Flow: page the arXiv API for recent cs.CL ids -> deterministic order via
seed 42 -> download e-print source (>=3s between EVERY arXiv request) ->
parse LaTeX -> aggregate per-section citation share/density and
per-sentence reference counts into backend/benchmarks/arxiv_cs_cl.json.

Re-runnable: raw downloads land in backend/benchmarks/.cache/ (gitignored)
and are reused; interrupted runs resume from cache. Papers whose e-print
is PDF-only or unparseable are skipped and more ids are drawn until the
target parses.

Metrics (mirrored by citecheck/distribution):
- section share  = cite keys in the section / all cite keys in the paper;
  a section that exists but has no cites contributes share 0, and absent
  sections contribute 0 too (share means therefore sum to ~1 across all
  canonical buckets including "other"). Density stats, which need words,
  are computed only over papers where the section is present.
- density        = cite keys per 1000 Latin word tokens of section text.
- sentence_refs  = per paper, share of citing sentences carrying >=2/3/5
  distinct cite keys; aggregated across papers as median/q1/q3.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import random
import re
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citecheck.parse.headings import canonical_for

log = logging.getLogger("build_benchmark")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

HERE = Path(__file__).resolve().parent.parent  # backend/
BENCH_DIR = HERE / "benchmarks"
CACHE_DIR = BENCH_DIR / ".cache"
OUT_PATH = BENCH_DIR / "arxiv_cs_cl.json"

ARXIV_API = "https://export.arxiv.org/api/query"
QUERY = "cat:cs.CL AND submittedDate:[202410010000 TO 202609302359]"
GAP = 3.0  # seconds between arXiv requests, process-wide
SEED = 42
CANONICALS = ["intro", "related", "method", "experiment",
              "discussion", "conclusion", "other"]

_last_req = 0.0


def _throttle() -> None:
    global _last_req
    wait = GAP - (time.monotonic() - _last_req)
    if wait > 0:
        time.sleep(wait)
    _last_req = time.monotonic()


def _get(url: str, params: dict | None = None, retries: int = 3) -> bytes | None:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        _throttle()
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "citecheck-benchmark/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            log.warning("GET %s failed (%s), attempt %d", url, e, attempt + 1)
            time.sleep(5 * (attempt + 1))
    return None


# ------------------------------------------------------------------ pool

_ID_RE = re.compile(r"<id>https?://arxiv\.org/abs/([^<]+)</id>")


def fetch_pool(pool_size: int) -> list[str]:
    cache = CACHE_DIR / "pool.json"
    if cache.exists():
        ids = json.loads(cache.read_text())
        if len(ids) >= pool_size:
            log.info("pool from cache: %d ids", len(ids))
            return ids
    ids: list[str] = []
    start = 0
    while len(ids) < pool_size:
        data = _get(ARXIV_API, {
            "search_query": QUERY, "start": start,
            "max_results": min(100, pool_size - len(ids)),
            "sortBy": "submittedDate", "sortOrder": "descending",
        })
        if data is None:
            break
        page = _ID_RE.findall(data.decode("utf-8", "replace"))
        if not page:
            break
        ids += page
        start += len(page)
        log.info("pool: %d/%d", len(ids), pool_size)
    cache.write_text(json.dumps(ids))
    return ids


# ------------------------------------------------------------------ fetch

def fetch_eprint(arxiv_id: str) -> bytes | None:
    """Cached raw e-print download; None on network failure."""
    safe = arxiv_id.replace("/", "_")
    path = CACHE_DIR / f"{safe}.bin"
    if path.exists():
        return path.read_bytes()
    data = _get(f"https://arxiv.org/e-print/{arxiv_id}")
    if data is None:
        return None
    path.write_bytes(data)
    return data


# ------------------------------------------------------------------ latex

_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
_COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")
_CITE_RE = re.compile(
    r"\\(cite[a-zA-Z]*)\*?(?:\[[^\]]*\])*\s*\{([^}]*)\}"
)
_SECTION_RE = re.compile(r"\\section\*?\s*\{")

_EXCLUDE_CITE_PREFIXES = ("citeauthor", "citeyear")

_DROP_ENV = re.compile(
    r"\\begin\{(figure|table|tabular|equation|align|gather|multline|"
    r"eqnarray|displaymath)\*?\}.*?\\end\{\1\*?\}", re.S)
_MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$\n]*\$|\\\(.{0,2000}?\\\)|\\\[.*?\\\]", re.S)
_CMD_ARG_RE = re.compile(
    r"\\(?:label|ref|eqref|autoref|pageref|cite[a-zA-Z]*|url|footnote|index|"
    r"section|subsection|subsubsection|paragraph|subparagraph)\*?"
    r"(?:\[[^\]]*\])?\{[^}]*\}")
_CMD_RE = re.compile(r"\\[a-zA-Z]+\*?")
_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")


def _unroll_inputs(name: str, files: dict[str, str], seen: set[str]) -> str:
    """Inline \\input/\\include files (one level of the archive's names)."""
    text = files.get(name, "")
    def repl(m: re.Match) -> str:
        target = m.group(1).strip()
        if not target.endswith(".tex"):
            target += ".tex"
        for cand in (target, target.split("/")[-1]):
            if cand in files and cand not in seen:
                seen.add(cand)
                return _unroll_inputs(cand, files, seen)
        return ""
    return _INPUT_RE.sub(repl, text)


def _tex_sources(blob: bytes) -> dict[str, str] | None:
    """Extract {filename: text} from a tar.gz / gz / raw tex blob."""
    if blob[:2] == b"\x1f\x8b":
        try:
            blob = gzip.decompress(blob)
        except OSError:
            return None
    if blob[257:262] == b"ustar":
        try:
            with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                return {
                    m.name: tf.extractfile(m).read().decode("utf-8", "replace")
                    for m in tf.getmembers()
                    if m.isfile() and m.name.endswith(".tex")
                    and tf.extractfile(m) is not None
                }
        except tarfile.TarError:
            return None
    if blob.startswith(b"%PDF"):
        return None
    try:
        return {"main.tex": blob.decode("utf-8", "replace")}
    except Exception:  # noqa: BLE001
        return None


def _paper_text(files: dict[str, str]) -> str | None:
    """Main tex with inputs inlined, comments stripped, appendix/refs cut."""
    main = None
    for name, text in files.items():
        if "\\documentclass" in text and "\\begin{document}" in text:
            main = name
            break
    if main is None:
        return None
    body = _unroll_inputs(main, files, {main})
    body = _COMMENT_RE.sub("", body)
    for cut in (r"\appendix", r"\bibliography{", r"\bibliographystyle{",
                r"\begin{thebibliography}"):
        i = body.find(cut)
        if i >= 0:
            body = body[:i]
    return body


def _sections(body: str) -> list[tuple[str, str]]:
    """[(title, text)] split on \\section (starred included). Leading text
    before the first \\section keeps title '' (canonical other)."""
    heads = [(m.start(), m.end()) for m in _SECTION_RE.finditer(body)]
    out: list[tuple[str, str]] = []
    if heads and heads[0][0] > 0:
        out.append(("", body[: heads[0][0]]))
    for k, (s, e) in enumerate(heads):
        title_end = e
        depth = 1
        while title_end < len(body) and depth:
            if body[title_end] == "{":
                depth += 1
            elif body[title_end] == "}":
                depth -= 1
            title_end += 1
        title = body[e:title_end - 1]
        nxt = heads[k + 1][0] if k + 1 < len(heads) else len(body)
        out.append((title, body[title_end:nxt]))
    return out


def _cite_keys(text: str) -> list[str]:
    keys: list[str] = []
    for m in _CITE_RE.finditer(text):
        cmd = m.group(1).lower()
        if any(cmd.startswith(p) for p in _EXCLUDE_CITE_PREFIXES):
            continue
        keys += [k.strip() for k in m.group(2).split(",") if k.strip()]
    return keys


def _word_count(text: str) -> int:
    t = _DROP_ENV.sub(" ", text)
    t = _MATH_RE.sub(" ", t)
    t = _CMD_ARG_RE.sub(" ", t)
    t = _CMD_RE.sub(" ", t)
    t = re.sub(r"[{}]", " ", t)
    return len(_WORD_RE.findall(t))


_SENT_SPLIT = re.compile(r"[.!?;]+(?=\s|$)|\n\n+")


def _sentence_key_counts(text: str) -> list[int]:
    """Keys per citing sentence: replace cite commands by markers, split
    roughly on sentence punctuation, count keys per sentence."""
    marked = _CITE_RE.sub(
        lambda m: " \x01" + str(len([k for k in m.group(2).split(",") if k.strip()]))
                  + "\x02 "
        if not any(m.group(1).lower().startswith(p)
                   for p in _EXCLUDE_CITE_PREFIXES)
        else " ",
        text,
    )
    marked = _CMD_ARG_RE.sub(" ", marked)
    counts = []
    for sent in _SENT_SPLIT.split(marked):
        n = sum(int(x) for x in re.findall("\x01(\\d+)\x02", sent))
        if n:
            counts.append(n)
    return counts


# ------------------------------------------------------------------ stats

def _stats(vals: list[float]) -> dict:
    vals = sorted(vals)
    n = len(vals)

    def quantile(q: float) -> float:
        if n == 0:
            return 0.0
        pos = (n - 1) * q
        lo, hi = int(pos), min(int(pos) + 1, n - 1)
        return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)

    return {
        "mean": sum(vals) / n if n else 0.0,
        "median": quantile(0.5),
        "q1": quantile(0.25),
        "q3": quantile(0.75),
    }


def _iqr_stats(vals: list[float]) -> dict:
    s = _stats(vals)
    return {"median": s["median"], "q1": s["q1"], "q3": s["q3"]}


def parse_paper(blob: bytes) -> dict | None:
    files = _tex_sources(blob)
    if not files:
        return None
    body = _paper_text(files)
    if body is None:
        return None
    sections = _sections(body)
    per_section: dict[str, dict] = {}
    total_keys = 0
    sent_counts: list[int] = []
    for title, text in sections:
        canonical = canonical_for(title) if title else "other"
        sec = per_section.setdefault(canonical, {"keys": 0, "words": 0})
        keys = _cite_keys(text)
        sec["keys"] += len(keys)
        sec["words"] += _word_count(text)
        total_keys += len(keys)
        sent_counts += _sentence_key_counts(text)
    if total_keys == 0:
        return None
    return {
        "sections": per_section,
        "total_keys": total_keys,
        "sent_counts": sent_counts,
    }


def aggregate(papers: list[dict]) -> dict:
    n = len(papers)
    sections: dict[str, dict] = {}
    for canon in CANONICALS:
        shares = []
        densities = []
        present = 0
        for p in papers:
            sec = p["sections"].get(canon)
            if sec is None:
                shares.append(0.0)
                continue
            present += 1
            shares.append(sec["keys"] / p["total_keys"])
            if sec["words"] > 0:
                densities.append(sec["keys"] / sec["words"] * 1000)
        share = _stats(shares)
        sections[canon] = {
            "share": share,
            "density_per_1k_words": _iqr_stats(densities),
            "present_in": present,
        }
    sent_stats = {}
    for g, key in ((2, "share_ge2"), (3, "share_ge3"), (5, "share_ge5")):
        vals = [
            sum(1 for c in p["sent_counts"] if c >= g) / len(p["sent_counts"])
            for p in papers if p["sent_counts"]
        ]
        sent_stats[key] = _iqr_stats(vals)
    return {"sections": sections, "sentence_refs": sent_stats}


# ------------------------------------------------------------------ main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=150)
    ap.add_argument("--pool", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pool = fetch_pool(args.pool)
    order = pool[:]
    random.Random(args.seed).shuffle(order)
    log.info("pool=%d, drawing until %d papers parse", len(pool), args.target)

    papers: list[dict] = []
    paper_ids: list[str] = []
    skipped = 0
    for arxiv_id in order:
        if len(papers) >= args.target:
            break
        blob = fetch_eprint(arxiv_id)
        if blob is None:
            skipped += 1
            continue
        paper = parse_paper(blob)
        if paper is None:
            skipped += 1
            continue
        papers.append(paper)
        paper_ids.append(arxiv_id)
        if len(papers) % 10 == 0:
            log.info("parsed %d/%d (skipped %d)", len(papers), args.target,
                     skipped)

    log.info("done: %d parsed, %d skipped", len(papers), skipped)
    agg = aggregate(papers)
    out = {
        "id": "arxiv_cs_cl",
        "name": "arXiv 计算语言学",
        "language": "en",
        "n_papers": len(papers),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "paper_ids": paper_ids,
        "sections": agg["sections"],
        "sentence_refs": agg["sentence_refs"],
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    log.info("wrote %s (n_papers=%d)", OUT_PATH, len(papers))
    for canon in CANONICALS:
        s = agg["sections"][canon]
        log.info(
            "  %-10s share mean=%.3f med=%.3f [%.3f, %.3f] present=%d "
            "density med=%.2f", canon, s["share"]["mean"],
            s["share"]["median"], s["share"]["q1"], s["share"]["q3"],
            s["present_in"], s["density_per_1k_words"]["median"],
        )


if __name__ == "__main__":
    main()
