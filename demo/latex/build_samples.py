"""构建 LaTeX 样例集：下载 arXiv 源码 → 按 injections.json 注入错误 →
打包成 samples/<name>.zip。

    python demo/latex/build_samples.py            # 全部
    python demo/latex/build_samples.py bert lora  # 指定

arXiv 原始包缓存在 raw/（不进 git，arXiv 请求间隔 3 秒）。每处编辑的
find 必须在文件里恰好出现一次，否则报错退出，防止注入悄悄失效。
单个大于 500KB 的图片类文件不进样例包（解析不需要，仓库保持轻量）。
"""

from __future__ import annotations

import fnmatch
import io
import json
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
OUT = HERE / "samples"
SPEC = HERE / "injections.json"
_BIG = 500 * 1024
_BINARY = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".gif", ".svg")
_UA = "Clover-citecheck sample builder (research use)"


def fetch(arxiv_id: str) -> bytes:
    RAW.mkdir(exist_ok=True)
    path = RAW / f"{arxiv_id}.tar.gz"
    if not path.is_file():
        req = urllib.request.Request(
            f"https://arxiv.org/e-print/{arxiv_id}", headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=60) as resp:
            path.write_bytes(resp.read())
        time.sleep(3)  # arXiv politeness
    return path.read_bytes()


def unpack(blob: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            p = PurePosixPath(m.name)
            if p.is_absolute() or ".." in p.parts:
                continue
            f = tf.extractfile(m)
            if f is not None:
                files[p.as_posix()] = f.read()
    return files


def apply(files: dict[str, bytes], inj: dict) -> None:
    for e in inj["edits"]:
        name = e["file"]
        if name not in files:
            raise SystemExit(f"{inj['id']}: {name} 不在源码包里")
        text = files[name].decode("utf-8")
        if "append" in e:
            text += e["append"]
        else:
            n = text.count(e["find"])
            if n != 1:
                raise SystemExit(
                    f"{inj['id']}: {name} 中 find 出现 {n} 次（需要恰好 1 次）："
                    f"{e['find'][:60]!r}")
            text = text.replace(e["find"], e["replace"])
        files[name] = text.encode("utf-8")


def build(paper: dict) -> Path:
    files = unpack(fetch(paper["arxiv"]))
    for pat in paper.get("drop", []):
        for name in [n for n in files
                     if fnmatch.fnmatch(PurePosixPath(n).name, pat)]:
            del files[name]
    for name in [n for n, b in files.items()
                 if n.lower().endswith(_BINARY) and len(b) > _BIG]:
        del files[name]
    for inj in paper["injections"]:
        apply(files, inj)
    OUT.mkdir(exist_ok=True)
    out = OUT / f"{paper['name']}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            # fixed timestamp: rebuilding yields byte-identical zips
            info = zipfile.ZipInfo(f"{paper['name']}/{name}",
                                   date_time=(2026, 10, 6, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, files[name])
    return out


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    want = set(sys.argv[1:])
    for paper in spec["papers"]:
        if want and paper["name"] not in want:
            continue
        out = build(paper)
        print(f"{out.relative_to(HERE)}  {out.stat().st_size // 1024} KB  "
              f"{len(paper['injections'])} 处注入")


if __name__ == "__main__":
    main()
