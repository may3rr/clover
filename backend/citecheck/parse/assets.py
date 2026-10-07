"""Figure images extracted from a manuscript, stored for the reading view.

A bundle is one directory under ``<cache dir>/assets/<bundle>/``; the
server serves ``GET /assets/{bundle}/{name}``. Only formats a browser
shows are kept: PNG/JPEG/GIF/WebP are copied, PDF/EPS/TIFF/BMP (LaTeX
figures are usually PDF) are rendered to PNG with macOS ``sips``. Anything
else is skipped — the figure's caption still shows.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
from pathlib import Path

from ..config import get_settings

log = logging.getLogger(__name__)

_WEB = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_CONVERT = {".pdf", ".eps", ".tif", ".tiff", ".bmp"}
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_MAX_BYTES = 30 * 1024 * 1024


def assets_root() -> Path:
    return Path(get_settings().cache_path).parent / "assets"


def bundle_dir(bundle: str) -> Path | None:
    if not _NAME_RE.match(bundle):
        return None
    return assets_root() / bundle


def asset_path(bundle: str, name: str) -> Path | None:
    """Resolved file for a served asset, or None (bad name / missing)."""
    d = bundle_dir(bundle)
    if d is None or not _NAME_RE.match(name):
        return None
    p = (d / name).resolve()
    if p.parent != d.resolve() or not p.is_file():
        return None
    return p


def bundle_id(prefix: str, key: str | bytes) -> str:
    raw = key if isinstance(key, bytes) else key.encode("utf-8")
    return f"{prefix}{hashlib.sha256(raw).hexdigest()[:16]}"


class Bundle:
    """Writes images for one document; names are stable per source so a
    re-parse reuses the files already on disk."""

    def __init__(self, bundle: str):
        self.id = bundle
        self.dir = assets_root() / bundle
        self.used = False

    def _target(self, stem: str, ext: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-")[:48] or "img"
        return self.dir / f"{safe}{ext}"

    def add_bytes(self, data: bytes, stem: str, ext: str) -> str | None:
        ext = ext.lower()
        if len(data) > _MAX_BYTES:
            return None
        if ext in _WEB:
            out = self._target(stem, ".jpg" if ext == ".jpeg" else ext)
            if not out.is_file():
                self.dir.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            self.used = True
            return out.name
        if ext in _CONVERT:
            out = self._target(stem, ".png")
            if out.is_file():
                self.used = True
                return out.name
            self.dir.mkdir(parents=True, exist_ok=True)
            src = self.dir / f".src-{out.stem}{ext}"
            src.write_bytes(data)
            try:
                return self._convert(src, out)
            finally:
                src.unlink(missing_ok=True)
        return None

    def add_file(self, path: Path, stem: str) -> str | None:
        """Copy/convert a file; the content hash in the name keeps an
        edited figure from being served from a stale copy."""
        try:
            if path.stat().st_size > _MAX_BYTES:
                return None
            data = path.read_bytes()
        except OSError:
            return None
        digest = hashlib.sha256(data).hexdigest()[:8]
        return self.add_bytes(data, f"{stem[:39]}-{digest}", path.suffix)

    def _convert(self, src: Path, out: Path) -> str | None:
        # Quick Look renders vector PDFs at the requested size; sips only
        # rasterises at 72 dpi, so it is the fallback (TIFF/BMP, or when
        # qlmanage is unavailable)
        if src.suffix.lower() == ".pdf" and shutil.which("qlmanage"):
            tmp = self.dir / f".ql-{out.stem}"
            tmp.mkdir(exist_ok=True)
            try:
                subprocess.run(
                    ["qlmanage", "-t", "-s", "1400", "-o", str(tmp), str(src)],
                    check=True, capture_output=True, timeout=30)
                made = tmp / f"{src.name}.png"
                if made.is_file():
                    made.replace(out)
            except (subprocess.SubprocessError, OSError) as e:
                log.info("Quick Look render failed for %s: %s", src.name, e)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if not out.is_file() and shutil.which("sips"):
            try:
                subprocess.run(
                    ["sips", "-s", "format", "png", str(src), "--out", str(out)],
                    check=True, capture_output=True, timeout=30)
            except (subprocess.SubprocessError, OSError) as e:
                log.info("figure conversion failed for %s: %s", src.name, e)
        if not out.is_file():
            return None
        self.used = True
        return out.name
