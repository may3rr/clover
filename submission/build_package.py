"""组装决赛提交文件包：效率进化赛道-我要发顶刊-Clover：投稿前的论文引用体检/

    python submission/build_package.py [--incoming <dir>]

--incoming：从 Intel 决赛机拷来的文件夹。里面的 {NAME}.pdf（PowerPoint
导出）替换 LibreOffice 导出的 PDF，*.mp4 放进 演示视频/。

先启动网页复刻版的开发服务器（npm run site:dev，端口 5180），并且已经用
app/site/scripts/pitch-pptx.py 生成了可编辑的 PPTX。产物在
app/site-single/效率进化赛道-我要发顶刊-Clover：投稿前的论文引用体检/ 和同名 .zip（目录已被 git 忽略）。

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
import pypdf
import qrcode
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
NAME = "效率进化赛道-我要发顶刊-Clover：投稿前的论文引用体检"
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

EVID = "作品佐证材料"  # organizer: supporting files named by content title, in one folder
# (source, output, extra css); the project description must fit on one page
ONE_PAGE = ("@page { margin: 10mm 12mm; } body { font-size: 8.6pt; line-height: 1.45; } "
            "h1 { font-size: 15pt; } h2 { font-size: 10.5pt; margin: 7pt 0 3pt; } "
            "td, th { padding: 2pt 4pt; font-size: 8pt; } p, li { margin: 1.5pt 0; }")
DOC_PDFS = [
    ("01-项目说明.md", "项目说明.pdf", ONE_PAGE),
    ("05-赛期成果说明.md", "赛期成果说明.pdf", ""),
    ("03-作品链接与佐证.md", "作品链接与佐证.pdf", ""),
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
SHOTS_PITCH = ROOT / "demo" / "intel" / "shots-pitch"
# finals machine screenshots copied as is
MORE_SHOTS = [
    ("08-运行页.png", WIN_SHOTS / "light-running-mid.png"),
    ("13-隐私模式开关.png", SHOTS_PITCH / "04-settings-privacy.png"),
    ("14-发往云端清单.png", SHOTS_PITCH / "05-send-list.png"),
]
# frames of the finals-machine recording (seconds into the demo video)
VIDEO_SHOTS = [
    ("09-核对文献连接.png", 40),
    ("10-核对对标范文.png", 90),
    ("11-任务管理器-体检进行中.png", 220),
    ("12-导出Word-WPS中的批注.png", 940),
]
PROMO = [
    ("封面-1920x1080.png", ROOT / "submission" / "封面-1920x1080.png"),
    ("封面-3840x2160.png", ROOT / "submission" / "封面-3840x2160.png"),
    ("logo-1024.png", ROOT / "submission" / "logo-1024.png"),
    ("logo.svg", ROOT / "submission" / "logo.svg"),
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


# typeset with xelatex (submission/tex/clover.sty holds fonts, colours, layout)
TEX = ROOT / "submission" / "tex"
TEX_PDFS = [("tech.tex", "技术说明.pdf")]


def tex_pdfs() -> None:
    for src, dst in TEX_PDFS:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["latexmk", "-xelatex", "-interaction=nonstopmode", "-halt-on-error",
                            f"-outdir={tmp}", src], cwd=TEX, check=True, capture_output=True)
            shutil.copy(Path(tmp) / src.replace(".tex", ".pdf"), PKG / EVID / dst)
        print(dst, len(pypdf.PdfReader(PKG / EVID / dst).pages), "pages (xelatex)")


def doc_pdfs(pg) -> None:
    for src, dst, extra in DOC_PDFS:
        body = markdown.markdown((DOCS / src).read_text(), extensions=["tables"])
        html = f"<!doctype html><meta charset='utf-8'><style>{CSS}{extra}</style>{body}"
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(html)
        pg.goto(Path(f.name).as_uri())
        pg.wait_for_timeout(300)
        m = "10mm" if extra else "18mm"
        pg.pdf(path=str(PKG / EVID / dst), format="A4", print_background=True,
               margin={"top": m, "bottom": m, "left": "16mm" if not extra else "12mm",
                       "right": "16mm" if not extra else "12mm"})
        print(dst, len(pypdf.PdfReader(PKG / EVID / dst).pages), "pages")


# 项目介绍图文: cover, one paragraph, captioned screenshots (captions from 03's table)
INTRO_SHOTS = ["01-报告页.png", "09-核对文献连接.png", "02-文献真实性.png", "03-论断支持度.png",
               "04-格式规范.png", "05-期刊对标.png", "12-导出Word-WPS中的批注.png",
               "11-任务管理器-体检进行中.png", "14-发往云端清单.png"]


def intro_pdf(pg) -> None:
    import re
    md = (DOCS / "01-项目说明.md").read_text()
    one = md.split("## 一句话介绍", 1)[1].split("##", 1)[0].strip()
    caps = dict(re.findall(r"^\| (\d\d-[^|]+\.png) \| ([^|]+) \|", (DOCS / "03-作品链接与佐证.md").read_text(), re.M))
    shots_dir = PKG / EVID / "截图"
    figs = "".join(
        f"<figure><img src='{(shots_dir / n).as_uri()}'><figcaption>{caps.get(n, '').strip()}</figcaption></figure>"
        for n in INTRO_SHOTS)
    html = f"""<!doctype html><meta charset='utf-8'><style>{CSS}
      figure {{ margin: 0 0 14pt; break-inside: avoid; }}
      img {{ width: 100%; border-radius: 6pt; box-shadow: 0 0 0 0.5pt #ddd; }}
      figcaption {{ font-size: 9.5pt; color: #555; margin-top: 4pt; }}
      .cover {{ width: 100%; border-radius: 8pt; margin: 6pt 0 10pt; }}</style>
      <h1>Clover：投稿前的论文引用体检</h1>
      <p>效率进化赛道，阿里云特别赛题，Intel 本地 AI 应用挑战。团队：我要发顶刊，天津师范大学，吕浩博。产品主页 {HOME}</p>
      <img class='cover' src='{(PKG / EVID / "宣传素材" / "封面-1920x1080.png").as_uri()}'>
      <p>{one}</p>
      <h2>界面与真实运行</h2>{figs}"""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html)
    pg.goto(Path(f.name).as_uri())
    pg.wait_for_timeout(800)
    dst = PKG / EVID / "项目介绍图文.pdf"
    pg.pdf(path=str(dst), format="A4", print_background=True,
           margin={"top": "16mm", "bottom": "16mm", "left": "16mm", "right": "16mm"})
    print(dst.name, len(pypdf.PdfReader(dst).pages), "pages")


def shots(browser) -> None:
    out = PKG / EVID / "截图"
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
    for dst, src in MORE_SHOTS:
        shutil.copy(src, out / dst)
    videos = sorted((PKG / "演示视频").glob("*.mp4"))
    for dst, t in VIDEO_SHOTS if videos else []:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(videos[0]),
                        "-frames:v", "1", str(out / dst)], check=True)
        print(f"{dst}  {t}s of {videos[0].name}")
    promo = PKG / EVID / "宣传素材"
    promo.mkdir(exist_ok=True)
    for dst, src in PROMO:
        shutil.copy(src, promo / dst)


def main() -> None:
    import sys
    incoming = Path(sys.argv[sys.argv.index("--incoming") + 1]) if "--incoming" in sys.argv else None
    if not PPTX.exists():
        raise SystemExit(f"缺少 {PPTX}，先运行 app/site/scripts/pitch-pptx.py")
    shutil.rmtree(PKG, ignore_errors=True)
    PKG.mkdir(parents=True)
    (PKG / "演示视频").mkdir()
    (PKG / EVID).mkdir()

    shutil.copy(PPTX, PKG / PPTX.name)
    ppt_pdf = incoming / f"{NAME}.pdf" if incoming else None
    if ppt_pdf and ppt_pdf.exists():
        shutil.copy(ppt_pdf, PKG / f"{NAME}.pdf")
        print(f"{NAME}.pptx, {NAME}.pdf (PowerPoint export from the finals machine)")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", tmp,
                            str(PKG / PPTX.name)], check=True, capture_output=True)
            shutil.move(Path(tmp) / f"{NAME}.pdf", PKG / f"{NAME}.pdf")
        print(f"{NAME}.pptx, {NAME}.pdf (LibreOffice)")
    for v in sorted(incoming.glob("*.mp4")) if incoming else []:
        shutil.copy(v, PKG / "演示视频" / v.name)
        print(f"演示视频/{v.name}  {v.stat().st_size / 1e6:.0f} MB")

    qrcode.make(HOME, border=2, box_size=16).save(PKG / EVID / "主页二维码.png")
    tex_pdfs()

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        doc_pdfs(b.new_page())
        shots(b)
        intro_pdf(b.new_page())
        b.close()

    zip_path = shutil.make_archive(str(SITE / NAME), "zip", SITE, NAME)
    size = sum(f.stat().st_size for f in PKG.rglob("*") if f.is_file())
    print(f"{PKG}  {size / 1e6:.1f} MB\n{zip_path}")


if __name__ == "__main__":
    main()
