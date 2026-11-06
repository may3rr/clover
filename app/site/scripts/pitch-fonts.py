"""把模板附带的阿里巴巴普惠体子集化成 woff2，供路演稿 pitch.html 使用。

字集 = GB2312 全部汉字与符号 + ASCII + 路演稿源码里出现的其他字符。
原始 ttf 在仓库外的模板目录（每个约 8MB），只提交生成的 woff2。

    python app/site/scripts/pitch-fonts.py
"""
from pathlib import Path

from fontTools import subset

SITE = Path(__file__).resolve().parent.parent
SRC = SITE.parent.parent / "天猫Ai黑客松｜选手路演PPT模版" / "字体包"
OUT = SITE / "src" / "pitch" / "assets" / "fonts"

chars = set(chr(c) for c in range(0x20, 0x7F))
for hi in range(0xA1, 0xF8):
    for lo in range(0xA1, 0xFF):
        try:
            chars.add(bytes([hi, lo]).decode("gb2312"))
        except UnicodeDecodeError:
            pass
for f in [SITE / "pitch.html", *(SITE / "src" / "pitch").glob("*.ts")]:
    chars.update(f.read_text("utf-8"))
chars = {c for c in chars if c.isprintable()}

OUT.mkdir(parents=True, exist_ok=True)
for w in ("55-Regular", "65-Medium", "85-Bold"):
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    font = subset.load_font(str(SRC / f"AlibabaPuHuiTi-2-{w}.ttf"), opts)
    s = subset.Subsetter(opts)
    s.populate(text="".join(chars))
    s.subset(font)
    out = OUT / f"PuHuiTi-{w}.woff2"
    subset.save_font(font, str(out), opts)
    print(out.name, round(out.stat().st_size / 1e6, 2), "MB")
