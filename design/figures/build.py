#!/usr/bin/env python3
"""把 src/F*.html 渲染成矢量 PDF（1px = 1pt）和 3 倍 PNG，并合并一份总览 PDF。

用法：
    conda activate claude
    python presentation/build.py            # 全部
    python presentation/build.py F06 F12    # 只渲染指定编号
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
OUT_PDF = ROOT / "out" / "pdf"
OUT_PNG = ROOT / "out" / "png"
PREVIEW = ROOT / "out" / "全部图预览.pdf"


def render(names: list[str]) -> list[Path]:
    OUT_PDF.mkdir(parents=True, exist_ok=True)
    OUT_PNG.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("F*.html"))
    if names:
        files = [f for f in files if any(f.name.startswith(n) for n in names)]
    done: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1200, "height": 900}, device_scale_factor=3)
        for f in files:
            page.goto(f.as_uri())
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            box = page.locator(".fig").bounding_box()
            w, h = round(box["width"]), round(box["height"])
            page.locator(".fig").screenshot(path=str(OUT_PNG / f"{f.stem}.png"))
            pdf_path = OUT_PDF / f"{f.stem}.pdf"
            page.pdf(
                path=str(pdf_path),
                width=f"{w / 72:.4f}in",
                height=f"{h / 72:.4f}in",
                scale=4 / 3,
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                page_ranges="1",
            )
            done.append(pdf_path)
            print(f"[ok] {f.stem}  {w}×{h}")
        browser.close()
    return done


def merge_preview() -> None:
    writer = PdfWriter()
    for pdf in sorted(OUT_PDF.glob("F*.pdf")):
        for page in PdfReader(str(pdf)).pages:
            writer.add_page(page)
    with PREVIEW.open("wb") as handle:
        writer.write(handle)
    print(f"[preview] {PREVIEW}")


if __name__ == "__main__":
    render(sys.argv[1:])
    merge_preview()
