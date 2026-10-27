"""Download the open-access PDFs of each test paper's references into its
library folder (<paper>/ref/), so experiments can run on local full text.

Sources, in order: the arXiv PDF (arXiv id from the verified record), then
the open-access pdf_url of the verified record. arXiv requests are spaced
3 s apart; other hosts share a small pool. A file is kept only if it starts
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
    title = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", m.get("title") or "untitled").strip()[:120]
    authors = m.get("authors") or []
    first = authors[0] if authors else "anon"
    first = first.split(",")[0].strip() if "," in first else first.split()[-1] if first.split() else "anon"
    first = re.sub(r"[\\/:*?\"<>|_]+", "", first)[:30] or "anon"
    return f"{title}_{first}.pdf"


async def _get(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        r = await client.get(url, headers=UA, timeout=60)
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or not r.content.startswith(b"%PDF") or len(r.content) > MAX_BYTES:
        return None
    return r.content


async def fetch(papers: list[str]) -> None:
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
        return paper, rid, None, "failed" if urls else "no_source"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        jobs = []
        for paper in papers:
            rep = json.loads((TESTSET / "reports" / f"{paper}_clean.json").read_text("utf-8"))
            folder = _folder(paper)
            folder.mkdir(parents=True, exist_ok=True)
            linked = {l["ref_id"] for l in (rep.get("library") or {}).get("links", [])}
            for rc in rep["ref_checks"]:
                m = rc.get("matched") or {}
                if rc["ref_id"] in linked or not (m.get("arxiv_id") or m.get("pdf_url")):
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
            if done % 20 == 0 or done == len(jobs):
                MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
                print(f"{done}/{len(jobs)}", flush=True)
            if not name:
                print(f"  {paper} {rid}: {how}", flush=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("papers", nargs="*")
    ap.add_argument("--zh", action="store_true")
    args = ap.parse_args()
    papers = args.papers + (ZH if args.zh else [])
    asyncio.run(fetch(papers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
