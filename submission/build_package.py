"""组装决赛提交文件包：效率进化赛道-我要发顶刊-Clover/

    python submission/build_package.py

先启动网页复刻版的开发服务器（npm run site:dev，端口 5180），并且已经用
app/site/scripts/pitch-pptx.py 生成了可编辑的 PPTX。产物在
app/site-single/效率进化赛道-我要发顶刊-Clover/ 和同名 .zip（目录已被 git 忽略）。

- PPTX 原样复制，PDF 由同一份 PPTX 经 LibreOffice 导出
- submission/docs/01–03 渲染成 PDF，04（讲稿）不进包
- 主页二维码
- 截图：网页复刻版载入中文演示稿的真实报告，按 Windows 版界面渲染；
  Intel 决赛机任务管理器截图原样复制
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import markdown
import qrcode
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
NAME = "效率进化赛道-我要发顶刊-Clover"
SITE = ROOT / "app" / "site-single"
PKG = SITE / NAME
PPTX = SITE / f"{NAME}.pptx"
DOCS = ROOT / "submission" / "docs"
FONTS = ROOT / "app" / "site" / "src" / "pitch" / "assets" / "fonts"
INTEL = ROOT / "app" / "site" / "src" / "pitch" / "assets" / "intel"
HOME = "https://jackielyu.is-a.dev/clover/"
WIN_SHOTS = ROOT / "demo" / "intel" / "shots-pitch" / "win"  # finals machine, shots mode
APP = "http://localhost:5180/app.html"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"

DOC_PDFS = [
    ("01-项目说明.md", f"{NAME}-项目说明.pdf"),
    ("02-技术说明.md", f"{NAME}-技术说明.pdf"),
    ("03-作品链接与佐证.md", f"{NAME}-作品链接与佐证.pdf"),
]

# (file, replica state): the Chinese demo report, one finding open each
SHOTS = [
    ("01-报告页.png", "report"),
    ("02-文献真实性.png", "item:f40"),
    ("03-论断支持度.png", "item:f28"),
    ("04-格式规范.png", "item:v5"),
    ("05-期刊对标.png", "venue:f35"),
]
INTEL_SHOTS = [
    ("06-任务管理器-核显.png", "06-gpu-vector.png"),
    ("07-任务管理器-NPU.png", "01-taskmanager-active.png"),
]


CSS = f"""
@font-face {{ font-family: P; src: url('{(FONTS / 'PuHuiTi-55-Regular.woff2').as_uri()}'); font-weight: 400; }}
@font-face {{ font-family: P; src: url('{(FONTS / 'PuHuiTi-85-Bold.woff2').as_uri()}'); font-weight: 700; }}
@page {{ size: A4; margin: 18mm 16mm; }}
body {{ font-family: P, 'PingFang SC', sans-serif; font-size: 10.5pt; line-height: 1.7; color: #1f1f1f; }}
h1 {{ font-size: 20pt; margin: 0 0 6pt; }}
h2 {{ font-size: 13pt; margin: 16pt 0 6pt; color: #d70015; }}
h3 {{ font-size: 11pt; margin: 12pt 0 4pt; }}
table {{ border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 9.5pt; }}
th, td {{ border: 0.5pt solid #d8d8d8; padding: 4pt 6pt; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f4; }}
code {{ font-family: 'JetBrains Mono', Menlo, monospace; font-size: 8.5pt; }}
p, li {{ margin: 3pt 0; }}
"""


def doc_pdfs(pg) -> None:
    for src, dst in DOC_PDFS:
        body = markdown.markdown((DOCS / src).read_text(), extensions=["tables"])
        html = f"<!doctype html><meta charset='utf-8'><style>{CSS}</style>{body}"
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(html)
        pg.goto(Path(f.name).as_uri())
        pg.wait_for_timeout(300)
        pg.pdf(path=str(PKG / dst), format="A4", print_background=True,
               margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"})
        print(dst)


def shots(browser) -> None:
    out = PKG / "截图"
    out.mkdir(exist_ok=True)
    pg = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2,
                          user_agent=UA)
    for name, state in SHOTS:
        real = WIN_SHOTS / f"light-{state.replace(':', '-')}.png"
        if real.exists():
            shutil.copy(real, out / name)
            print(f"{name}  {state}  real Windows screenshot")
            continue
        pg.goto(f"{APP}?state={state}&data=zh")
        pg.wait_for_function("() => window.clover && window.clover.ready", timeout=30000)
        pg.wait_for_timeout(1500)
        opened = pg.evaluate(
            "() => (document.querySelector('.detail-in')?.innerText ?? '').split('\\n')"
            ".filter(Boolean).slice(0, 2).join(' | ')")
        pg.screenshot(path=str(out / name))
        print(f"{name}  {state}  {opened or '-'}")
    pg.close()
    for dst, src in INTEL_SHOTS:
        shutil.copy(INTEL / src, out / dst)


def main() -> None:
    if not PPTX.exists():
        raise SystemExit(f"缺少 {PPTX}，先运行 app/site/scripts/pitch-pptx.py")
    shutil.rmtree(PKG, ignore_errors=True)
    PKG.mkdir(parents=True)
    (PKG / "演示视频").mkdir()

    shutil.copy(PPTX, PKG / PPTX.name)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", tmp,
                        str(PKG / PPTX.name)], check=True, capture_output=True)
        shutil.move(Path(tmp) / f"{NAME}.pdf", PKG / f"{NAME}.pdf")
    print(f"{NAME}.pptx, {NAME}.pdf")

    qrcode.make(HOME, border=2, box_size=16).save(PKG / f"{NAME}-主页二维码.png")

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        doc_pdfs(b.new_page())
        shots(b)
        b.close()

    zip_path = shutil.make_archive(str(SITE / NAME), "zip", SITE, NAME)
    size = sum(f.stat().st_size for f in PKG.rglob("*") if f.is_file())
    print(f"{PKG}  {size / 1e6:.1f} MB\n{zip_path}")


if __name__ == "__main__":
    main()
