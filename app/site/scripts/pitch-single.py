"""把路演稿打成一个可以直接双击打开的 HTML 单文件。

  1. 用 vite.single.config.ts 分别构建 app.html（Clover 网页复刻版）和
     pitch.html，所有脚本、样式、字体、图片都内联成 data URI。
  2. 复刻版要读的报告数据（public/data/*.json）作为 window.__CLOVER_DATA__
     写进它的页面。
  3. 复刻版整页作为字符串 window.__APP_HTML__ 放进路演稿；路演稿用 iframe
     srcdoc 加载它，所以不需要服务器，也不访问网络。

    python app/site/scripts/pitch-single.py            # 输出 app/site-single/Clover-路演.html
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
APP = SITE.parent
OUT_DIR = APP / "site-single"
OUT = OUT_DIR / "Clover-路演.html"


def build(entry: str) -> Path:
    env = {**os.environ, "SINGLE_ENTRY": entry}
    subprocess.run(["npx", "vite", "build", "--config", "site/vite.single.config.ts"],
                   cwd=APP, env=env, check=True, stdout=subprocess.DEVNULL)
    return OUT_DIR / entry / f"{entry}.html"


def script_safe(code: str) -> str:
    """Code placed inside <script>…</script> must not close the tag early."""
    return code.replace("</script", "<\\/script").replace("<!--", "<\\!--")


def inline(html_path: Path) -> str:
    """Replace the built page's external <script src> and <link stylesheet>
    with inline copies (vite has already inlined every asset into them)."""
    html = html_path.read_text("utf-8")
    base = html_path.parent

    def js(m: re.Match) -> str:
        code = (base / m.group(1)).read_text("utf-8")
        return f'<script type="module">{script_safe(code)}</script>'

    def css(m: re.Match) -> str:
        return f"<style>{(base / m.group(1)).read_text('utf-8')}</style>"

    html = re.sub(r'<script type="module" crossorigin src="\./([^"]+)"></script>', js, html)
    html = re.sub(r'<link rel="stylesheet" crossorigin href="\./([^"]+)">', css, html)
    html = re.sub(r'<link rel="icon"[^>]*>', "", html)
    if re.search(r'(src|href)="\./assets/', html):
        sys.exit(f"{html_path.name}: an asset was not inlined")
    return html


def main() -> None:
    app = inline(build("app"))
    data = {
        "showcase": json.loads((SITE / "public/data/showcase.json").read_text("utf-8")),
        "grounded": json.loads((SITE / "public/data/grounded.json").read_text("utf-8")),
        "outline": json.loads((SITE / "public/data/showcase_outline.json").read_text("utf-8")),
    }
    data_js = "window.__CLOVER_DATA__ = " + json.dumps(data, ensure_ascii=False) + ";"
    app = app.replace("<head>", f"<head><script>{script_safe(data_js)}</script>", 1)

    deck = inline(build("pitch"))
    app_js = "window.__APP_HTML__ = " + json.dumps(app, ensure_ascii=False) + ";"
    deck = deck.replace("<head>", f"<head><script>{script_safe(app_js)}</script>", 1)
    OUT.write_text(deck, "utf-8")
    print(f"{OUT}  {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
