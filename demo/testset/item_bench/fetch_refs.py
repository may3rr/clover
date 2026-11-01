"""Download the open-access PDFs of each test paper's references into its
library folder (<paper>/ref/), so experiments can run on local full text.

Sources, in order: the arXiv PDF (arXiv id from the verified record), then
the open-access pdf_url of the verified record, then an arXiv title search
(export.arxiv.org API, accepted only when the normalised titles match) for
entries with neither or whose downloads failed. arXiv requests are spaced
3 s apart; every download has a hard 120 s limit so one slow transfer cannot
hold the arXiv slot; other hosts share a small pool. A file is kept only if it starts
with %PDF. Files are named "<title>_<first author>.pdf", the CNKI habit the
library linker already reads. Which file belongs to which reference is
recorded in library_manifest.json next to this script.

Usage:
    python demo/testset/item_bench/fetch_refs.py liuqiao_kg luohuilan_odt ...
    python demo/testset/item_bench/fetch_refs.py --zh      # the four zh papers with a ref/ folder
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
TESTSET = HERE.parent
MANIFEST = HERE / "library_manifest.json"
ZH = ["liuqiao_kg", "luohuilan_odt", "yinhongpeng_odt", "zhaoyangyang_tod", "guyingjie_mrc"]
UA = {"User-Agent": "citecheck-testset/0.1 (research benchmark; polite single-file downloads)"}
MAX_BYTES = 60_000_000


def _folder(paper: str) -> Path:
    base = TESTSET / ("en_papers" if paper.startswith("en_") else "zh_papers")
    return base / paper.removeprefix("en_") / "ref" if paper.startswith("en_") else base / paper / "ref"


def _name(m: dict) -> str:
    title = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ",
                   m.get("title") or m.get("_ms_title") or "untitled").strip()[:120]
    authors = m.get("authors") or m.get("_ms_authors") or []
    first = authors[0] if authors else "anon"
    first = first.split(",")[0].strip() if "," in first else first.split()[-1] if first.split() else "anon"
    first = re.sub(r"[\\/:*?\"<>|_]+", "", first)[:30] or "anon"
    return f"{title}_{first}.pdf"


async def _get(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        r = await asyncio.wait_for(client.get(url, headers=UA, timeout=60), 120)
    except (httpx.HTTPError, asyncio.TimeoutError):
        return None
    if r.status_code != 200 or not r.content.startswith(b"%PDF") or len(r.content) > MAX_BYTES:
        return None
    return r.content


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


async def _arxiv_search(client: httpx.AsyncClient, title: str) -> str | None:
    """arXiv id whose title matches ``title`` exactly after normalising."""
    words = re.findall(r"[A-Za-z0-9]+", title or "")
    if len(words) < 3:
        return None
    q = "+AND+".join(f"ti:{w}" for w in words[:12])
    try:
        r = await asyncio.wait_for(client.get(
            f"https://export.arxiv.org/api/query?search_query={q}&max_results=5",
            headers=UA, timeout=30), 45)
    except (httpx.HTTPError, asyncio.TimeoutError):
        return None
    if r.status_code != 200:
        return None
    want = _norm_title(title)
    for entry in re.findall(r"<entry>(.*?)</entry>", r.text, flags=re.S):
        t = re.search(r"<title>(.*?)</title>", entry, flags=re.S)
        i = re.search(r"<id>https?://arxiv.org/abs/([^<]+?)(v\d+)?</id>", entry)
        if t and i and _norm_title(re.sub(r"\s+", " ", t.group(1))) == want:
            return i.group(1)
    return None


async def fetch(papers: list[str], reports: str = "reports") -> None:
    manifest = json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {}
    arxiv_lock = asyncio.Lock()
    pool = asyncio.Semaphore(4)

    async def one(client, paper: str, rid: str, m: dict, folder: Path) -> tuple[str, str, str | None, str]:
        dest = folder / _name(m)
        if dest.exists():
            return paper, rid, dest.name, "exists"
        urls = []
        if m.get("arxiv_id"):
            urls.append(("arxiv", f"https://arxiv.org/pdf/{m['arxiv_id']}"))
        if m.get("pdf_url"):
            urls.append(("oa", m["pdf_url"]))
        for kind, url in urls:
            if kind == "arxiv" or "arxiv.org" in url:
                async with arxiv_lock:
                    data = await _get(client, url)
                    await asyncio.sleep(3)
            else:
                async with pool:
                    data = await _get(client, url)
            if data:
                dest.write_bytes(data)
                return paper, rid, dest.name, kind
        title = m.get("title") or m.get("_ms_title")
        if title and not m.get("arxiv_id"):
            async with arxiv_lock:
                aid = await _arxiv_search(client, title)
                await asyncio.sleep(3)
                data = await _get(client, f"https://arxiv.org/pdf/{aid}") if aid else None
                if aid:
                    await asyncio.sleep(3)
            if data:
                dest.write_bytes(data)
                return paper, rid, dest.name, "arxiv_search"
        return paper, rid, None, "failed" if urls else "no_source"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        jobs = []
        for paper in papers:
            rep = json.loads((TESTSET / reports / f"{paper}_clean.json").read_text("utf-8"))
            folder = _folder(paper)
            folder.mkdir(parents=True, exist_ok=True)
            linked = {l["ref_id"] for l in (rep.get("library") or {}).get("links", [])}
            ms_title = {r["id"]: r.get("title") for r in rep["references"]}
            ms_auth = {r["id"]: r.get("authors") or [] for r in rep["references"]}
            for rc in rep["ref_checks"]:
                m = dict(rc.get("matched") or {})
                m["_ms_title"] = ms_title.get(rc["ref_id"])
                m["_ms_authors"] = ms_auth.get(rc["ref_id"])
                if not m.get("title") and not m["_ms_title"]:
                    continue
                if rc["ref_id"] in linked:
                    continue
                if manifest.get(paper, {}).get(rc["ref_id"]):
                    continue
                jobs.append(one(client, paper, rc["ref_id"], m, folder))
        print(f"{len(jobs)} downloads queued")
        done = 0
        for fut in asyncio.as_completed(jobs):
            paper, rid, name, how = await fut
            done += 1
            if name:
                manifest.setdefault(paper, {})[rid] = name
            if done % 5 == 0 or done == len(jobs):
                MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
                print(f"{done}/{len(jobs)}", flush=True)
            if not name:
                print(f"  {paper} {rid}: {how}", flush=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("papers", nargs="*")
    ap.add_argument("--zh", action="store_true")
    ap.add_argument("--reports", default="reports",
                    help="folder (under demo/testset) holding <paper>_clean.json")
    args = ap.parse_args()
    papers = args.papers + (ZH if args.zh else [])
    asyncio.run(fetch(papers, args.reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
