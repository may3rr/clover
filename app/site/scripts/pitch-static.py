"""把路演稿导出成静态 PPTX：每一步的最终画面截成 3840×2160 的图，一张图一页。

会场只能用 PPT，并且不再放动画，所以用这份静态版。需要先启动网页复刻版的
开发服务器（npm run site:dev，端口 5180）。

    python app/site/scripts/pitch-static.py     # 输出 app/site-single/Clover-路演.pptx
"""
from __future__ import annotations

import io
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright
from pptx import Presentation
from pptx.util import Emu

URL = "http://localhost:5180/pitch.html"
OUT = Path(__file__).resolve().parents[2] / "site-single" / "Clover-路演.pptx"

# (page, actions, keep): a number waits that many seconds after the page or
# the last key and takes a shot; "k" advances one step; "pose" freezes the
# last-mile page in a still that tells the story without motion. keep = which shots
# become slides (1-based); None keeps all.
PLAN = [
    (1, [2.0], None),
    (2, [3.5, "k", 11.5, "pose", 0.5], [3]),  # 最后一公里：火箭停在初稿前，人走在半路
    (3, ["k", 2.0], None),                  # 真实错引
    (4, [9.0, 18.0], None),                 # 运行页（千问与英特尔）、报告
    (5, [8.0, "k", 4.0, "k", 4.0, "k", 4.0], None),  # 四类问题各一页
    (6, ["k", "k", 2.5], None),             # 凭什么可靠
    (7, [1.5], None),                       # 四项检查总览
    (8, ["k", "k", 1.5], None),             # 论断支持度怎么核对
    (9, ["k", 1.5], None),                  # Intel 必填页
    (10, ["k", 1.5], None),                 # 隐私
    (11, [2.0], None),                      # THANKS
]


POSE = """() => {
  const el = document.querySelector('.slide.on')
  const set = (sel, x) => {
    const n = el.querySelector(sel)
    n.getAnimations().forEach((a) => a.cancel())
    n.style.opacity = '1'
    n.style.transform = `translateX(${x}px)`
  }
  set('.rocket', 730)      // nose just short of 初稿
  set('.walker', 1185)     // halfway from 初稿 to 投稿
  el.querySelector('.walker').classList.remove('walking')
}"""


def shots() -> list[bytes]:
    out: list[bytes] = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
        for page, acts, keep in PLAN:
            pg.goto(f"{URL}#{page}")
            pg.reload()
            time.sleep(0.3)
            t0, got = time.time(), []
            for a in acts:
                if a == "pose":
                    pg.evaluate(POSE)
                    t0 = time.time()
                    continue
                if a == "k":
                    time.sleep(0.6)
                    pg.keyboard.press("ArrowRight")
                    t0 = time.time()
                    continue
                time.sleep(max(0.0, a - (time.time() - t0)))
                got.append(pg.screenshot())
            out += [g for i, g in enumerate(got, 1) if keep is None or i in keep]
            print(f"page {page}: {len(got)} shots")
        b.close()
    return out


def main() -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    blank = prs.slide_layouts[6]
    for png in shots():
        buf = io.BytesIO()
        Image.open(io.BytesIO(png)).convert("RGB").save(buf, "JPEG", quality=90)
        buf.seek(0)
        s = prs.slides.add_slide(blank)
        s.shapes.add_picture(buf, 0, 0, prs.slide_width, prs.slide_height)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"{OUT}  {len(prs.slides)} slides  {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
