"""LaTeX 压缩包（.zip / .tar.gz / .tgz / arXiv 单文件 .gz）安全解压。

解压目标在缓存目录下按文件内容哈希命名，同一个包只解压一次；原压缩
包只读不改。防护：拒绝绝对路径、``..``、符号链接与设备文件；总解压
体积与文件数设上限；跳过 macOS 的 ``__MACOSX`` 与 ``._*`` 资源叉。
"""

from __future__ import annotations

import gzip
import hashlib
import io
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from ...config import get_settings

ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".tar", ".gz")
_MAX_TOTAL = 400 * 1024 * 1024
_MAX_FILES = 5000


class ArchiveError(ValueError):
    pass


def is_archive(path: Path) -> bool:
    name = path.name.lower()
    return path.is_file() and name.endswith(ARCHIVE_SUFFIXES)


def archive_stem(path: Path) -> str:
    name = path.name
    for suf in (".tar.gz", ".tgz", ".zip", ".tar", ".gz"):
        if name.lower().endswith(suf):
            return name[: -len(suf)]
    return path.stem


def _safe_rel(name: str) -> PurePosixPath | None:
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return None
    if p.parts[0] == "__MACOSX" or p.name.startswith("._") \
            or p.name == ".DS_Store":
        return None
    return p


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()[:20]


def _extract_zip(src: Path, dest: Path) -> None:
    total = 0
    with zipfile.ZipFile(src) as zf:
        infos = zf.infolist()
        if len(infos) > _MAX_FILES:
            raise ArchiveError("压缩包内文件过多")
        for info in infos:
            if info.is_dir():
                continue
            # 高 16 位是 unix mode：符号链接一律跳过
            mode = info.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                continue
            rel = _safe_rel(info.filename)
            if rel is None:
                continue
            total += info.file_size
            if total > _MAX_TOTAL:
                raise ArchiveError("压缩包解压后体积过大")
            out = dest.joinpath(*rel.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as fin, out.open("wb") as fout:
                shutil.copyfileobj(fin, fout)


def _extract_tar(fileobj, dest: Path) -> None:
    total = 0
    with tarfile.open(fileobj=fileobj, mode="r:*") as tf:
        members = tf.getmembers()
        if len(members) > _MAX_FILES:
            raise ArchiveError("压缩包内文件过多")
        for m in members:
            if not m.isfile():
                continue
            rel = _safe_rel(m.name)
            if rel is None:
                continue
            total += m.size
            if total > _MAX_TOTAL:
                raise ArchiveError("压缩包解压后体积过大")
            fin = tf.extractfile(m)
            if fin is None:
                continue
            out = dest.joinpath(*rel.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            with fin, out.open("wb") as fout:
                shutil.copyfileobj(fin, fout)


def extract_archive(src: str | Path, base: Path | None = None) -> Path:
    """解压到 ``<缓存目录>/latex/<内容哈希>/``，返回该目录。"""
    src = Path(src)
    base = base or Path(get_settings().cache_path).parent / "latex"
    dest = base / _digest(src)
    done = dest / ".clover-extracted"
    if done.is_file():
        return dest
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        name = src.name.lower()
        if zipfile.is_zipfile(src):
            _extract_zip(src, tmp)
        elif name.endswith((".tar.gz", ".tgz", ".tar")) or tarfile.is_tarfile(src):
            with src.open("rb") as fh:
                _extract_tar(fh, tmp)
        elif name.endswith(".gz"):
            # arXiv 单文件投稿：e-print 是 gzip 压缩的单个 .tex，或 tar.gz
            data = gzip.decompress(src.read_bytes())
            if len(data) > _MAX_TOTAL:
                raise ArchiveError("压缩包解压后体积过大")
            try:
                _extract_tar(io.BytesIO(data), tmp)
            except tarfile.TarError:
                (tmp / (archive_stem(src) + ".tex")).write_bytes(data)
        else:
            raise ArchiveError("无法识别的压缩格式")
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ArchiveError(f"压缩包无法读取：{e}") from e
    except ArchiveError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    done.write_text(str(src), encoding="utf-8")
    return dest
