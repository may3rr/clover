"""Cover title -> full product name; footer (logo + product name) on slides 2-15.

The footer is one transparent PNG so the PPTX and the PDF carry the same pixels:
it is added to the PPTX as a picture and stamped onto the PowerPoint-exported PDF.
usage: python pitch-footer.py <deck.pptx> <deck.pdf>
"""
import io
import sys
from pathlib import Path

import pypdf
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Emu
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[3]
NAME = "Clover：投稿前的论文引用体检"
FONTS = Path.home() / "Library" / "Fonts"
EMU_PT = 12700
# footer box, EMU: left edge of the content frame, between frame bottom and the red bar
FX, FY, FH = 1_360_000, 6_300_000, 210_000
FIRST, LAST = 1, 14  # 0-based slide indices that get the footer


def footer_png() -> Image.Image:
    s = 8  # px per pt
    h = int(FH / EMU_PT * s)
    font = ImageFont.truetype(str(FONTS / "AlibabaPuHuiTi-2-55-Regular.ttf"), int(h * 0.62))
    logo = Image.open(ROOT / "submission" / "logo-512.png").convert("RGBA").resize((h, h), Image.LANCZOS)
    tw = int(font.getlength(NAME))
    img = Image.new("RGBA", (h + int(h * 0.4) + tw + 4, h), (0, 0, 0, 0))
    img.alpha_composite(logo, (0, 0))
    d = ImageDraw.Draw(img)
    d.text((h + int(h * 0.4), h / 2), NAME, font=font, fill=(255, 255, 255, 190), anchor="lm")
    return img


def text_w(txt: str, pt: float) -> float:
    f = ImageFont.truetype(str(FONTS / "AlibabaPuHuiTi-2-85-Bold.ttf"), 400)
    return f.getlength(txt) / 400 * pt * EMU_PT


def cover(prs) -> None:
    s = prs.slides[0]
    by = {sh.name: sh for sh in s.shapes}
    t = by["文本框 5"]
    run = t.text_frame.paragraphs[0].runs[0]
    old_l = t.left + (t.width - text_w(run.text, 40)) / 2
    old_r = old_l + text_w(run.text, 40)
    cx = t.left + t.width / 2
    pt = 34
    new_w = text_w(NAME, pt)
    run.text = NAME
    run.font.size = Emu(pt * EMU_PT)
    t.width = int(new_w + 400_000)
    t.left = int(cx - t.width / 2)
    new_l, new_r = cx - new_w / 2, cx + new_w / 2
    for n in ("矩形 11", "矩形 12"):
        by[n].left = int(by[n].left - old_l + new_l)
    for n in ("矩形 13", "矩形 14", "矩形 15"):
        by[n].left = int(by[n].left - old_r + new_r)


def main() -> None:
    pptx, pdf = Path(sys.argv[1]), Path(sys.argv[2])
    png = footer_png()
    buf = io.BytesIO()
    png.save(buf, "PNG")
    fw = int(FH * png.width / png.height)

    prs = Presentation(pptx)
    cover(prs)
    for i in range(FIRST, LAST + 1):
        buf.seek(0)
        prs.slides[i].shapes.add_picture(buf, FX, FY, fw, FH)
    prs.save(pptx)

    r = pypdf.PdfReader(pdf)
    w = pypdf.PdfWriter()
    for i, page in enumerate(r.pages):
        if FIRST <= i <= LAST:
            pw, ph = float(page.mediabox.width), float(page.mediabox.height)
            k = pw / (prs.slide_width / EMU_PT)
            ov = io.BytesIO()
            c = canvas.Canvas(ov, pagesize=(pw, ph))
            c.drawImage(ImageReader(png), FX / EMU_PT * k, ph - (FY + FH) / EMU_PT * k,
                        fw / EMU_PT * k, FH / EMU_PT * k, mask="auto")
            c.save()
            page.merge_page(pypdf.PdfReader(ov).pages[0])
        w.add_page(page)
    w.write(pdf)
    print(f"cover title -> {NAME}; footer on slides {FIRST + 1}-{LAST + 1}")


if __name__ == "__main__":
    main()
