"""路演稿导出成可编辑的 PPTX，基于大赛官方模板。

组委会要求提交可编辑的 .pptx，版式以官方模板为准。这个脚本打开模板，
封面和 THANKS 直接改模板页上的文字，内容页用模板第 2 页（Intel 必填页）
的背景和标题框，页面内容从 HTML 演示稿 app/site/pitch.html 每一步的最终
画面读出来：文字写成文本框，色块写成形状，图标、示意图和软件窗口截成
透明底的图片。HTML 演示稿的背景比模板放大了 10%，坐标按模板换算回来。

需要先启动网页复刻版的开发服务器（npm run site:dev，端口 5180）。

    python app/site/scripts/pitch-pptx.py
        -> app/site-single/效率进化赛道-我要发顶刊-Clover.pptx

软件窗口优先用 Intel 决赛机上用截图模式拍的真实 Windows 截图
（demo/intel/shots-pitch/win/），没有时才用网页复刻版渲染。
"""
from __future__ import annotations

import copy
import io
import time
from pathlib import Path

from lxml import etree
from playwright.sync_api import sync_playwright
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "天猫Ai黑客松｜选手路演PPT模版" / "路演PPT模版.pptx"
OUT = ROOT / "app" / "site-single" / "效率进化赛道-我要发顶刊-Clover.pptx"
URL = "http://localhost:5180/pitch.html"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

FONT = "阿里巴巴普惠体 2.0"
MONO = "JetBrains Mono"
PX = 6350  # EMU per px on the 1920 × 1080 canvas

# Real screenshots from the Windows finals machine (app shots mode, see
# demo/intel/shots-pitch/win/README.md). When present they replace the
# rendered app window on these stills, in PLAN order.
WIN_SHOTS = ROOT / "demo" / "intel" / "shots-pitch" / "win"
WIN_STATES = {  # (page, still number) -> shots-mode state
    (4, 1): "running-mid", (4, 2): "report",
    (5, 1): "item:f40", (5, 2): "item:f28", (5, 3): "item:v5", (5, 4): "item:f35",
}


def real_shot(page: int, n: int) -> bytes | None:
    state = WIN_STATES.get((page, n))
    if not state:
        return None
    f = WIN_SHOTS / f"light-{state.replace(':', '-')}.png"
    return f.read_bytes() if f.exists() else None


# (page, actions, keep, title): see pitch-static.py; title None = template
# cover / THANKS, handled separately
PLAN = [
    (2, [3.5, "k", 11.5, "pose", 0.5], [3], "投稿前的最后一公里"),
    (3, ["k", 2.0], None, None),
    (4, [9.0, 18.0], None, None),
    (5, [8.0, "k", 4.0, "k", 4.0, "k", 4.0], None, None),
    (6, ["k", "k", 2.5], None, None),
    (7, [1.5], None, None),
    (8, ["k", "k", 1.5], None, None),
    (9, ["k", 1.5], None, "Intel本地AI应用挑战"),
    (10, ["k", 1.5], None, None),
    (11, [2.0], None, None),
]

# whole elements taken as one picture: animated drawings and app windows
IMAGE_SEL = ".mile, .win, .flow svg.fw, .flow .ibadge img"
SKIP_SEL = ".bar-title, .foot, .cursor, .docx"

POSE = """() => {
  const el = document.querySelector('.slide.on')
  const set = (sel, x) => {
    const n = el.querySelector(sel)
    n.getAnimations().forEach((a) => a.cancel())
    n.style.opacity = '1'
    n.style.transform = `translateX(${x}px)`
  }
  set('.rocket', 730)
  set('.walker', 1185)
  el.querySelector('.walker').classList.remove('walking')
}"""

EXTRACT = r"""(opts) => {
  const slide = document.querySelector('.slide.on')
  const deck = document.querySelector('#deck').getBoundingClientRect()
  const out = []
  let pid = 0
  const rgba = (s) => {
    const m = (s || '').match(/rgba?\(([^)]+)\)/)
    if (!m) return null
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number)
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }
  }
  const R = (r) => ({ x: r.left - deck.left, y: r.top - deck.top, w: r.width, h: r.height })
  const opac = (el) => {
    let o = 1
    for (let e = el; e && e !== document.body; e = e.parentElement) o *= Number(getComputedStyle(e).opacity)
    return o
  }
  const visible = (el) => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e)
      if (cs.display === 'none' || cs.visibility === 'hidden') return false
    }
    return opac(el) > 0.05
  }
  const sized = (el) => { const r = el.getBoundingClientRect(); return r.width > 0.5 && r.height > 0.5 }
  // flattened colour behind an element (for blending translucent text)
  const under = (el) => {
    const stack = []
    for (let e = el; e; e = e.parentElement) {
      const c = rgba(getComputedStyle(e).backgroundColor)
      if (c && c.a > 0) stack.push(c)
    }
    let col = { r: 30, g: 22, b: 24 }
    for (const c of stack.reverse()) col = { r: col.r * (1 - c.a) + c.r * c.a, g: col.g * (1 - c.a) + c.g * c.a, b: col.b * (1 - c.a) + c.b * c.a }
    return col
  }
  const textColor = (el) => {
    const c = rgba(getComputedStyle(el).color) || { r: 255, g: 255, b: 255, a: 1 }
    const a = c.a * opac(el)
    const u = under(el)
    return [c.r * a + u.r * (1 - a), c.g * a + u.g * (1 - a), c.b * a + u.b * (1 - a)].map(Math.round)
  }
  const style = (el) => {
    const cs = getComputedStyle(el)
    return {
      size: parseFloat(cs.fontSize), bold: Number(cs.fontWeight) >= 600,
      color: textColor(el), mono: /Mono|monospace/.test(cs.fontFamily),
      sup: cs.verticalAlign === 'super' || el.tagName === 'SUP',
    }
  }
  const para = (el) => {
    const cs = getComputedStyle(el)
    const lh = cs.lineHeight === 'normal' ? parseFloat(cs.fontSize) * 1.25 : parseFloat(cs.lineHeight)
    return { align: cs.textAlign, lh, nowrap: cs.whiteSpace === 'nowrap' }
  }
  const box = (el) => {
    const cs = getComputedStyle(el)
    const bg = rgba(cs.backgroundColor)
    let ring = null
    const m = cs.boxShadow.match(/(rgba?\([^)]+\))\s+0px\s+0px\s+0px\s+([\d.]+)px\s+inset/)
    if (m) ring = { c: rgba(m[1]), w: parseFloat(m[2]) }
    const bw = parseFloat(cs.borderTopWidth)
    if (!ring && bw > 0 && cs.borderTopStyle !== 'none') ring = { c: rgba(cs.borderTopColor), w: bw }
    if (((bg && bg.a > 0.01) || ring) && sized(el)) {
      const o = opac(el)
      out.push({ t: 'box', ...R(el.getBoundingClientRect()), bg: bg && bg.a > 0.01 ? { ...bg, a: bg.a * o } : null,
                 ring: ring ? { ...ring, c: { ...ring.c, a: ring.c.a * o } } : null,
                 radius: parseFloat(cs.borderTopLeftRadius) || 0 })
    }
  }
  const isImg = (el) => el.matches(opts.img) || ['IMG', 'IFRAME', 'CANVAS'].includes(el.tagName) || el.tagName.toLowerCase() === 'svg'
  const img = (el) => {
    if (!sized(el)) return
    el.dataset.pid = String(++pid)
    out.push({ t: 'img', pid, win: el.matches('.win'), ...R(el.getBoundingClientRect()) })
  }
  const inlineKid = (n) => n.nodeType === 3 || (n.nodeType === 1 && /^inline/.test(getComputedStyle(n).display) &&
    [...n.childNodes].every(inlineKid))
  // one text box with styled runs for a block whose content is all inline
  const rich = (el) => {
    const runs = []
    const walkIn = (n) => {
      if (n.nodeType === 3) {
        const t = n.textContent.replace(/\s+/g, ' ')
        if (t) runs.push({ text: t, ...style(n.parentElement) })
        return
      }
      if (n.nodeType !== 1 || !visible(n)) return
      if (n.tagName === 'BR') { runs.push({ text: '\n', ...style(el) }); return }
      // a highlight box drifts once PowerPoint re-measures the line: the
      // highlighted words become coloured bold text, masked words ■
      if (n.classList.contains('redact')) {
        runs.push({ ...style(el), text: '■'.repeat(n.textContent.trim().length), color: [140, 138, 132] })
        return
      }
      if (n.tagName === 'MARK') {
        const bg = rgba(getComputedStyle(n).backgroundColor)
        runs.push({ ...style(n), text: n.textContent, bold: true,
                    color: bg && bg.g > bg.r ? [30, 126, 52] : [215, 0, 21] })
        return
      }
      if (n !== el) box(n)
      if (isImg(n)) { img(n); return }
      n.childNodes.forEach(walkIn)
    }
    el.childNodes.forEach(walkIn)
    while (runs.length && !runs[0].text.trim()) runs.shift()
    if (runs.length) runs[0].text = runs[0].text.replace(/^ /, '')
    if (runs.length) runs[runs.length - 1].text = runs[runs.length - 1].text.replace(/ $/, '')
    if (runs.some((r) => r.text.trim())) out.push({ t: 'text', ...R(el.getBoundingClientRect()), runs, ...para(el) })
  }
  const walk = (el) => {
    if (!visible(el) || el.matches(opts.skip)) return
    if (isImg(el)) { img(el); return }
    box(el)
    const cs = getComputedStyle(el)
    const kids = [...el.childNodes]
    const hasText = kids.some((n) => n.nodeType === 3 && n.textContent.trim())
    const flow = !/flex|grid/.test(cs.display)
    if (flow && kids.every(inlineKid) && (hasText || el.innerText.trim())) { rich(el); return }
    for (const n of kids) {
      if (n.nodeType === 3 && n.textContent.trim()) {
        const r = document.createRange(); r.selectNodeContents(n)
        out.push({ t: 'text', ...R(r.getBoundingClientRect()),
                   runs: [{ text: n.textContent.trim().replace(/\s+/g, ' '), ...style(el) }], ...para(el), nowrap: true })
      } else if (n.nodeType === 1) walk(n)
    }
  }
  ;[...slide.children].forEach(walk)
  return out
}"""

ISOLATE = """(pid) => {
  let st = document.getElementById('iso')
  if (!st) { st = document.createElement('style'); st.id = 'iso'; document.head.appendChild(st) }
  st.textContent = pid === null ? '' :
    `html, body, #deck, .slide { background: transparent !important; }
     body * { visibility: hidden !important; }
     [data-pid="${pid}"], [data-pid="${pid}"] * { visibility: visible !important; }`
}"""


def capture() -> list[dict]:
    """[{title, items, images: {pid: png}}] for every content still."""
    stills = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2,
                        user_agent=UA)
        for page, acts, keep, title in PLAN:
            pg.goto(f"{URL}#{page}")
            pg.reload()
            time.sleep(0.3)
            t0, n = time.time(), 0
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
                n += 1
                if keep is not None and n not in keep:
                    continue
                items = pg.evaluate(EXTRACT, {"img": IMAGE_SEL, "skip": SKIP_SEL})
                images = {}
                for it in items:
                    if it["t"] != "img":
                        continue
                    pg.evaluate(ISOLATE, it["pid"])
                    clip = {"x": it["x"], "y": it["y"], "width": it["w"], "height": it["h"]}
                    images[it["pid"]] = pg.screenshot(clip=clip, omit_background=True)
                    pg.evaluate(ISOLATE, None)
                pg.evaluate("() => document.querySelectorAll('[data-pid]').forEach(e => delete e.dataset.pid)")
                real = real_shot(page, n)
                if real:
                    for it in items:
                        if it["t"] == "img" and it.get("win"):
                            images[it["pid"]] = real
                            print(f"  page {page} still {n}: real Windows screenshot")
                head = pg.evaluate("() => document.querySelector('.slide.on .bar-title')?.innerText ?? ''")
                stills.append({"title": title or head, "items": items, "images": images})
            print(f"page {page}: {n} stills")
        b.close()
    return stills


# --------------------------------------------------------------- pptx

def T(v: float) -> int:
    """HTML px (template background enlarged 10%, centred) -> template EMU."""
    return round(v / 1.1 * PX)


def TX(x: float) -> int:
    return round((x + 96) / 1.1 * PX)


def TY(y: float) -> int:
    return round((y + 54) / 1.1 * PX)


def pt(px: float) -> Pt:
    return Pt(px * 0.5 / 1.1)


def set_font(run, family: str) -> None:
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rpr, qn(tag))
        el.set("typeface", family)


def add_box(slide, it) -> None:
    w, h = max(T(it["w"]), PX), max(T(it["h"]), PX)
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if it["radius"] > 0.5 else MSO_SHAPE.RECTANGLE,
        TX(it["x"]), TY(it["y"]), w, h)
    if it["radius"] > 0.5:
        shape.adjustments[0] = min(0.5, it["radius"] / max(1.0, min(it["w"], it["h"])))
    shape.shadow.inherit = False
    bg = it["bg"]
    if bg:
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(round(bg["r"]), round(bg["g"]), round(bg["b"]))
        if bg["a"] < 0.995:
            srgb = shape.fill._xPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
            etree.SubElement(srgb, qn("a:alpha")).set("val", str(round(bg["a"] * 100000)))
    else:
        shape.fill.background()
    ring = it["ring"]
    if ring:
        c = ring["c"]
        shape.line.color.rgb = RGBColor(round(c["r"]), round(c["g"]), round(c["b"]))
        shape.line.width = Emu(T(ring["w"]))
        if c["a"] < 0.995:
            srgb = shape.line._get_or_add_ln().find(qn("a:solidFill")).find(qn("a:srgbClr"))
            etree.SubElement(srgb, qn("a:alpha")).set("val", str(round(c["a"] * 100000)))
    else:
        shape.line.fill.background()
    shape.text_frame.text = ""


ALIGN = {"center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT, "end": PP_ALIGN.RIGHT}


def add_text(slide, it, transform=True) -> None:
    fx, fy, fs = (TX, TY, T) if transform else ((lambda v: round(v * PX)),) * 3
    x, w = it["x"], it["w"]
    # PowerPoint measures text a little wider than Chrome: give room so
    # a line does not wrap where the browser did not
    one_line = it["h"] < it["lh"] * 1.6
    slack = (0.06 * w + 8) if (one_line or it["nowrap"]) else 0.03 * w
    if it["align"] == "center":
        x -= slack / 2
    elif it["align"] in ("right", "end"):
        x -= slack
    w += slack
    tb = slide.shapes.add_textbox(fx(x), fy(it["y"]), fs(w), fs(it["h"]))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.word_wrap = not it["nowrap"]
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = MSO_ANCHOR.TOP
    k = 1.0 if transform else 1.1
    paras = [[]]
    for r in it["runs"]:
        parts = r["text"].split("\n")
        for i, part in enumerate(parts):
            if i:
                paras.append([])
            if part:
                paras[-1].append({**r, "text": part})
    for i, runs in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = ALIGN.get(it["align"], PP_ALIGN.LEFT)
        p.line_spacing = Pt(it["lh"] * 0.5 / 1.1 * k)
        for r in runs:
            run = p.add_run()
            run.text = r["text"]
            f = run.font
            f.size = Pt(r["size"] * 0.5 / 1.1 * k)
            f.bold = r["bold"]
            f.color.rgb = RGBColor(*r["color"])
            set_font(run, MONO if r["mono"] else FONT)
            if r["sup"]:
                run._r.get_or_add_rPr().set("baseline", "30000")


def add_img(slide, it, png: bytes, transform=True) -> None:
    if transform:
        slide.shapes.add_picture(io.BytesIO(png), TX(it["x"]), TY(it["y"]), T(it["w"]), T(it["h"]))
    else:
        slide.shapes.add_picture(io.BytesIO(png), round(it["x"] * PX), round(it["y"] * PX),
                                 round(it["w"] * PX), round(it["h"] * PX))


def fill(slide, still, transform=True) -> None:
    for it in still["items"]:
        if it["t"] == "box":
            add_box(slide, it) if transform else None
        elif it["t"] == "text":
            add_text(slide, it, transform)
        elif it["t"] == "img":
            add_img(slide, it, still["images"][it["pid"]], transform)


def set_text(shape, text: str) -> None:
    """Replace a template text box's words, keeping its first run's format."""
    tf = shape.text_frame
    p0 = tf.paragraphs[0]
    runs = p0.runs
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    # the template names a font that is not installed; use the bundled one
    for r in p0.runs:
        set_font(r, FONT)


def thanks_sign() -> dict:
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2, user_agent=UA)
        pg.goto(f"{URL}#12")
        pg.reload()
        time.sleep(2.0)
        items = pg.evaluate(EXTRACT, {"img": IMAGE_SEL,
                                      "skip": SKIP_SEL + ", .thanks-art, .thanks-word, .thanks-date"})
        images = {}
        for it in items:
            if it["t"] == "img":
                pg.evaluate(ISOLATE, it["pid"])
                images[it["pid"]] = pg.screenshot(
                    clip={"x": it["x"], "y": it["y"], "width": it["w"], "height": it["h"]},
                    omit_background=True)
                pg.evaluate(ISOLATE, None)
        b.close()
    return {"items": [i for i in items if i["t"] != "box"], "images": images}


def main() -> None:
    stills = capture()
    sign = thanks_sign()

    prs = Presentation(str(TEMPLATE))
    slides = list(prs.slides)
    cover, intel, thanks = slides[0], slides[1], slides[5]

    # cover: the template's own text boxes
    texts = {s.name: s for s in cover.shapes if s.has_text_frame}
    set_text(texts["文本框 4"], "效率进化赛道")
    set_text(texts["文本框 5"], "Clover")
    set_text(texts["文本框 6"], "我要发顶刊")
    set_text(texts["文本框 7"], "学校名称：天津师范大学")
    set_text(texts["文本框 8"], "吕浩博")

    # THANKS: the date (the template's fraction slashes render as fractions), then the team sign
    for s in thanks.shapes:
        if s.has_text_frame and "THANKS" not in s.text_frame.text and s.text_frame.text.strip():
            set_text(s, "2026/09/08-11/08")
            for r in s.text_frame.paragraphs[0].runs:
                set_font(r, MONO)
    for s in thanks.shapes:
        if s.has_text_frame and "THANKS" in s.text_frame.text:
            for r in s.text_frame.paragraphs[0].runs:
                set_font(r, FONT)
                r.font.bold = True
    fill(thanks, sign, transform=False)

    # content pages: template page 2's background picture and title box
    bg_pic = next(s for s in intel.shapes if s.shape_type == 13)
    bg_blob = bg_pic.image.blob
    title_sp = next(s for s in intel.shapes if s.has_text_frame and "Intel" in s.text_frame.text)
    note_sp = next(s for s in intel.shapes if s.has_text_frame and "必填页" in s.text_frame.text)
    note_sp._element.getparent().remove(note_sp._element)
    layout = intel.slide_layout

    new_ids = []
    for still in stills:
        s = prs.slides.add_slide(layout)
        for ph in list(s.placeholders):
            ph._element.getparent().remove(ph._element)
        s.shapes.add_picture(io.BytesIO(bg_blob), 0, 0, prs.slide_width, prs.slide_height)
        t = copy.deepcopy(title_sp._element)
        s.shapes._spTree.append(t)
        title = s.shapes[-1]
        set_text(title, still["title"])
        for r in title.text_frame.paragraphs[0].runs:
            r.font.bold = True
            r.font.color.rgb = RGBColor(0x1B, 0x1B, 0x1B)
        fill(s, still)
        new_ids.append(prs.slides._sldIdLst[-1])

    # order: cover, content pages, THANKS; drop the template's other pages
    lst = prs.slides._sldIdLst
    ids = list(lst)
    cover_id, intel_id, thanks_id = ids[0], ids[1], ids[5]
    for sid in ids[1:6]:
        lst.remove(sid)
        if sid is not thanks_id:
            prs.part.drop_rel(sid.rId)
    for sid in new_ids:
        lst.remove(sid)
    for sid in new_ids:
        lst.append(sid)
    lst.append(thanks_id)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"{OUT}  {len(prs.slides)} slides  {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
