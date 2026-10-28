"""Retrieval accuracy of the excerpt builder: BM25 vs Qwen3 embeddings.

    python retrieval_eval.py [--gold RUN] [--models M1,M2]

Gold is the evidence sentence a full-text run located (default
pilot_full): the model read the whole paper, so the gold does not favour
any retrieval method. Each method ranks the same 3-sentence windows as
``support/sources.py::_bm25_excerpt`` and fills the same budget with the
same greedy rule; a hit means the excerpt covers at least half of the
gold sentence. Window embeddings come from SiliconFlow (key in
SILICONFLOW_API_KEY) and are cached under runs/emb/.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

import bench  # noqa: E402
from citecheck.cache import Cache  # noqa: E402
from citecheck.config import get_settings  # noqa: E402
from citecheck.library.source import _drop_reference_tail  # noqa: E402
from citecheck.support.claims import split_sentences  # noqa: E402
from citecheck.support.evidence import locate_evidence  # noqa: E402
from citecheck.support.judge import search_terms  # noqa: E402
from citecheck.support.sources import (  # noqa: E402
    _ARXIV_STAMP, _looks_like_ref_entry, _tokenize,
)

EMB_DIR = HERE / "runs" / "emb"
API = "https://api.siliconflow.cn/v1/embeddings"
HEAD = 600
# (budget chars, max windows): first pass and review, as in production
BUDGETS = {"首轮 2500": (2500, 5), "复核 6000": (6000, 12)}
INSTRUCT = ("Instruct: Given a claim from a survey paper, retrieve the passage "
            "of the cited paper that supports or contradicts it\nQuery: ")


class Paper:
    def __init__(self, pdf):
        body = _drop_reference_tail(pdf.body()[0])
        self.text = _ARXIV_STAMP.sub(lambda m: " " * len(m.group(0)), body)
        sents = split_sentences(self.text)
        lead = 0
        while lead < len(sents) and sents[lead].end < HEAD:
            lead += 1
        self.sents, self.lead = sents, lead
        self.lead_end = sents[lead - 1].end if lead else 0
        self.windows = [
            (i, " ".join(s.text for s in sents[i:i + 3]))
            for i in range(lead, len(sents))
        ]
        self.windows = [(i, w) for i, w in self.windows if not _looks_like_ref_entry(w)]


def _select(paper: Paper, scores: np.ndarray, budget: int, max_parts: int) -> list[int]:
    room = budget - paper.lead_end
    taken: list[int] = []
    used = 0
    for k in np.argsort(-scores, kind="stable"):
        if scores[k] <= 0:
            break
        i, w = paper.windows[k]
        if any(abs(i - j) < 3 for j in taken):
            continue
        taken.append(i)
        used += len(w) + 1
        if used >= room or len(taken) >= max_parts:
            break
    return taken


def _covered(paper: Paper, taken: list[int], span: tuple[int, int]) -> bool:
    s, e = span
    ranges = [(0, paper.lead_end)] + [
        (paper.sents[i].start, paper.sents[min(i + 2, len(paper.sents) - 1)].end)
        for i in taken
    ]
    hit = sum(max(0, min(e, b) - max(s, a)) for a, b in ranges)
    return hit >= 0.5 * (e - s)


def _bm25(paper: Paper, query: str) -> np.ndarray:
    from rank_bm25 import BM25Okapi

    bm = BM25Okapi([_tokenize(w) for _, w in paper.windows])
    return np.asarray(bm.get_scores(_tokenize(query)), dtype=float)


def _rrf(*score_lists: np.ndarray, k: int = 60) -> np.ndarray:
    out = np.zeros_like(score_lists[0])
    for sc in score_lists:
        ranks = np.empty(len(sc))
        ranks[np.argsort(-sc, kind="stable")] = np.arange(len(sc))
        out += 1.0 / (k + ranks + 1)
    return out


class Embedder:
    def __init__(self, model: str, key: str):
        self.model, self.key = model, key
        self.path = EMB_DIR / (re.sub(r"\W", "_", model) + ".npz")
        self.vecs: dict[str, np.ndarray] = {}
        if self.path.exists():
            z = np.load(self.path)
            self.vecs = dict(zip(z["keys"].tolist(), z["vecs"]))
        self.tokens = 0

    def save(self) -> None:
        EMB_DIR.mkdir(parents=True, exist_ok=True)
        keys = list(self.vecs)
        np.savez(self.path, keys=np.array(keys), vecs=np.stack([self.vecs[k] for k in keys]))

    async def embed(self, texts: list[str]) -> np.ndarray:
        want = [t for t in dict.fromkeys(texts) if _h(t) not in self.vecs]
        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(timeout=60) as client:
            async def batch(chunk: list[str]) -> None:
                async with sem:
                    for attempt in range(4):
                        try:
                            r = await client.post(
                                API, headers={"Authorization": f"Bearer {self.key}"},
                                json={"model": self.model, "input": chunk})
                            r.raise_for_status()
                            break
                        except httpx.HTTPError:
                            if attempt == 3:
                                raise
                            await asyncio.sleep(2 * (attempt + 1))
                    d = r.json()
                    self.tokens += d.get("usage", {}).get("total_tokens", 0)
                    for t, item in zip(chunk, sorted(d["data"], key=lambda x: x["index"])):
                        v = np.asarray(item["embedding"], dtype=np.float32)
                        self.vecs[_h(t)] = v / (np.linalg.norm(v) or 1.0)
            await asyncio.gather(*(batch(want[i:i + 32]) for i in range(0, len(want), 32)))
        if want:
            self.save()
        return np.stack([self.vecs[_h(t)] for t in texts])


def _h(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="pilot_full")
    ap.add_argument("--models", default="Qwen/Qwen3-Embedding-0.6B,Qwen/Qwen3-Embedding-4B")
    args = ap.parse_args()
    key = os.environ.get("SILICONFLOW_API_KEY")
    if not key:
        print("SILICONFLOW_API_KEY is not set")
        return 1

    items = {i["id"]: i for i in bench._load(bench.ITEMS)}
    rows = bench._rows(args.gold)
    src = bench._Sources(Cache(get_settings().cache_path), {items[k]["paper"] for k in rows})
    papers: dict[tuple[str, str], Paper] = {}
    gold = []
    for k, r in rows.items():
        it = items[k]
        if (it["kind"] == "swap" or r["off_topic"] or not r.get("evidence")
                or r["label"] not in ("supported", "partial", "unsupported")):
            continue
        pkey = (it["paper"], it["ref_id"])
        if pkey not in src.local:
            continue
        if pkey not in papers:
            papers[pkey] = Paper(src.local[pkey])
        span = locate_evidence(r["evidence"], papers[pkey].text)
        if span is None or not papers[pkey].windows:
            continue
        gold.append((k, it, pkey, span))
    in_head = sum(span[1] <= papers[p].lead_end for _, _, p, span in gold)
    print(f"gold {len(gold)} 条，其中 {in_head} 条在开头 {HEAD} 字内")

    queries = {}
    for k, it, _, _ in gold:
        terms = await search_terms(it["claim"], it.get("sentence"))
        queries[k] = (it["claim"], " ".join([it["claim"], *terms]))

    methods: dict[str, dict[str, np.ndarray]] = defaultdict(dict)
    for k, it, p, _ in gold:
        methods["BM25 论断+检索词"][k] = _bm25(papers[p], queries[k][1])
    for model in [m for m in args.models.split(",") if m]:
        emb = Embedder(model, key)
        short = model.split("-")[-1]
        for p, paper in papers.items():
            await emb.embed([w for _, w in paper.windows])
        qv = await emb.embed([INSTRUCT + q for k in queries for q in queries[k]])
        qmap = {}
        for n, k in enumerate(queries):
            qmap[k] = (qv[2 * n], qv[2 * n + 1])
        for k, it, p, _ in gold:
            wv = await emb.embed([w for _, w in papers[p].windows])
            s_claim, s_terms = wv @ qmap[k][0], wv @ qmap[k][1]
            methods[f"{short} 论断"][k] = s_claim + 1.0
            methods[f"{short} 论断+检索词"][k] = s_terms + 1.0
            methods[f"{short}+BM25 融合"][k] = _rrf(s_terms, methods["BM25 论断+检索词"][k])
        print(f"{model}: 新调用 {emb.tokens} tokens")

    body = [g for g in gold if g[3][1] > papers[g[2]].lead_end]
    print(f"\n只统计不在开头的 {len(body)} 条 gold：")
    print("| 方法 | " + " | ".join(BUDGETS) + " |")
    print("| --- |" + " --- |" * len(BUDGETS))
    for name, sc in methods.items():
        cells = []
        for budget, parts in BUDGETS.values():
            hits = sum(_covered(papers[p], _select(papers[p], sc[k], budget, parts), span)
                       for k, _, p, span in body)
            cells.append(f"{hits}/{len(body)} = {hits / len(body):.2f}")
        print(f"| {name} | " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
