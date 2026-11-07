"""Replace the two model-flow diagrams in the pitch PPTX with one picture each.

    python app/site/scripts/pitch-pptx-flatten.py   (after pitch-pptx.py, with npm run site:dev)

pitch-pptx.py rebuilds these pages from many small text boxes and pills; in
PowerPoint the pills drift off their labels. Here the whole diagram (.ov on
page 7, .flow on page 8 at its last step) is screenshotted with a transparent
background and placed where the boxes were; the template background and the
title bar stay as they are.
"""
from __future__ import annotations

import importlib.util
import io
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from pptx import Presentation

spec = importlib.util.spec_from_file_location("pp", Path(__file__).with_name("pitch-pptx.py"))
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)

# (html page, right-arrow presses, element, slide title)
PAGES = [
    (7, 0, ".ov", "四项检查，各用什么模型"),
    (8, 2, ".flow", "论断支持度，怎么核对"),
]
ONLY = """(sel) => {
  const keep = document.querySelector('.slide.on ' + sel)
  keep.dataset.keep = '1'
  const st = document.createElement('style')
  st.textContent = `html, body, #deck, .slide { background: transparent !important; }
    body *:not([data-keep], [data-keep] *) { visibility: hidden !important; }
    [data-keep], [data-keep] * { visibility: visible !important; }`
  document.head.appendChild(st)
  const r = keep.getBoundingClientRect()
  return { x: r.x, y: r.y, w: r.width, h: r.height }
}"""


def capture() -> dict[str, tuple[dict, bytes]]:
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2,
                        user_agent=pp.UA)
        for page, presses, sel, title in PAGES:
            pg.goto(f"{pp.URL}#{page}")
            pg.reload()
            time.sleep(1.0)
            for _ in range(presses):
                pg.keyboard.press("ArrowRight")
                time.sleep(0.8)
            time.sleep(2.5)  # let the entrance animations finish
            r = pg.evaluate(ONLY, sel)
            # include the badge and arrows that overhang the box
            pad = 40
            r = {"x": r["x"] - pad, "y": r["y"] - pad, "w": r["w"] + 2 * pad, "h": r["h"] + 2 * pad}
            png = pg.screenshot(clip={"x": r["x"], "y": r["y"], "width": r["w"], "height": r["h"]},
                                omit_background=True)
            out[title] = (r, png)
            print(f"page {page} {sel}: {r['w']:.0f} x {r['h']:.0f}")
        b.close()
    return out


def main() -> None:
    shots = capture()
    prs = Presentation(str(pp.OUT))
    done = 0
    for slide in prs.slides:
        titles = [s.text_frame.text for s in slide.shapes if s.has_text_frame]
        hit = next((t for t in shots if t in titles), None)
        if not hit:
            continue
        r, png = shots[hit]
        shapes = list(slide.shapes)
        # keep the background picture (first) and the title box; drop the diagram pieces
        for s in shapes[1:]:
            if s.has_text_frame and s.text_frame.text == hit:
                continue
            s._element.getparent().remove(s._element)
        slide.shapes.add_picture(io.BytesIO(png), pp.TX(r["x"]), pp.TY(r["y"]), pp.T(r["w"]), pp.T(r["h"]))
        done += 1
        print(f"flattened: {hit}  (removed {len(shapes) - 2} shapes)")
    assert done == len(PAGES), done
    prs.save(pp.OUT)
    print(pp.OUT)


if __name__ == "__main__":
    main()
