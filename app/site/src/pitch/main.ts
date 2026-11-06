/** Clover 路演稿的播放器。
 *
 *  → 空格 PageDown 回车：下一步（同一页内的分步动画走完再翻页）
 *  ← PageUp：上一页        R：重放本页        F：全屏        H：页码
 *  地址栏 #3 直接打开第 3 页。
 *
 *  第「拖入论文」页把 Clover 的网页复刻版（app.html）嵌在窗口里，用合成的
 *  拖放事件驱动它：画面上的运行页和报告都是应用自己的界面。 */
import './pitch.css'
import logoUrl from './assets/logo.svg'

const deck = document.getElementById('deck') as HTMLElement
const hud = document.getElementById('hud') as HTMLElement
const slides = Array.from(deck.querySelectorAll<HTMLElement>('.slide'))
const IS_WIN = /Windows/.test(navigator.userAgent)
/** set by scripts/pitch-single.py: the whole app page, inlined */
const APP_HTML = (window as { __APP_HTML__?: string }).__APP_HTML__ ?? null

// ---------------------------------------------------------------- layout

function fit() {
  const s = Math.min(innerWidth / 1920, innerHeight / 1080)
  deck.style.transform = `scale(${s}) translate(-50%, -50%)`
}
addEventListener('resize', fit)
fit()

// ---------------------------------------------------------------- helpers

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
/** each slide run gets a token; a newer run cancels the older one's awaits */
let runId = 0
class Cancelled extends Error {}
async function sleep(ms: number, id: number) {
  await wait(ms)
  if (id !== runId) throw new Cancelled()
}
function anim(el: Element, frames: Keyframe[], opts: KeyframeAnimationOptions) {
  return el.animate(frames, { fill: 'forwards', ...opts })
}

// ---------------------------------------------------------------- slides

type Hook = { enter?: (el: HTMLElement, id: number) => Promise<void>; step?: (el: HTMLElement, n: number, id: number) => Promise<void> }
const hooks: Record<string, Hook> = {
  最后一公里: {
    async enter(el, id) {
      const rocket = el.querySelector('.rocket') as SVGElement
      const trail = el.querySelector('.trail') as SVGElement
      const walker = el.querySelector('.walker') as SVGElement
      const stns = Array.from(el.querySelectorAll<HTMLElement>('.stn'))
      el.querySelectorAll('.lit, .show').forEach((n) => n.classList.remove('lit', 'show'))
      for (const n of [rocket, trail, walker]) n.getAnimations().forEach((a) => a.cancel())
      walker.classList.remove('walking')
      stns[0].classList.add('lit')
      await sleep(600, id)
      // the rocket's nose rides the trail head: x 90 → 1060 in the track box
      const dur = 1700
      anim(rocket, [{ opacity: 0, transform: 'translateX(-198px)' }, { opacity: 1, offset: 0.08 }, { opacity: 1, transform: 'translateX(772px)' }], { duration: dur, easing: 'cubic-bezier(0.5, 0, 0.2, 1)' })
      anim(trail, [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: dur, easing: 'cubic-bezier(0.5, 0, 0.2, 1)' })
      // stations light as the rocket passes (same easing, sampled)
      const pos = [332, 575, 818, 1060].map((x) => (x - 90) / 970)
      const ease = (t: number) => cubic(0.5, 0, 0.2, 1, t)
      const t0 = performance.now()
      for (let i = 0; i < pos.length; i++) {
        while (ease(Math.min(1, (performance.now() - t0) / dur)) < pos[i]) await sleep(16, id)
        stns[i + 1].classList.add('lit')
      }
      el.querySelector('.seg-fast')?.classList.add('show')
      await sleep(500, id)
      anim(rocket, [{ opacity: 1, transform: 'translateX(772px)' }, { opacity: 0, transform: 'translateX(870px)' }], { duration: 500, easing: 'ease-out' })
    },
    async step(el, n, id) {
      if (n !== 1) return
      const walker = el.querySelector('.walker') as SVGElement
      el.querySelector('.seg-slow')?.classList.add('show')
      walker.classList.add('walking')
      const a = anim(walker, [{ opacity: 0, transform: 'translateX(1020px)' }, { opacity: 1, offset: 0.05 }, { opacity: 1, transform: 'translateX(1350px)' }], { duration: 9000, easing: 'linear' })
      await a.finished.catch(() => {})
      if (id !== runId) return
      walker.classList.remove('walking')
      el.querySelector('.stn-end')?.classList.add('lit')
    },
  },

  四类问题: {
    async enter(el, id) {
      const frame = el.querySelector('.app-frame') as HTMLIFrameElement
      markLeaf(el, 0)
      await loadApp(frame, 'report', id)
      await sleep(900, id)
      await openFinding(frame, FINDINGS[0], id)
    },
    async step(el, n, id) {
      const frame = el.querySelector('.app-frame') as HTMLIFrameElement
      markLeaf(el, n)
      await openFinding(frame, FINDINGS[n], id)
    },
  },
  拖入论文: {
    async enter(el, id) {
      const frame = el.querySelector('.app-frame') as HTMLIFrameElement
      const docx = el.querySelector('.docx') as HTMLElement
      const cursor = el.querySelector('.cursor') as SVGElement
      const win = el.querySelector('.win') as HTMLElement
      for (const n of [docx, cursor, win]) n.getAnimations().forEach((a) => a.cancel())
      el.querySelector('.checks')?.classList.remove('show')
      await loadApp(frame, 'empty', id)
      await sleep(900, id)
      // cursor → file → drag into the window → drop
      const at = (x: number, y: number) => `translate(${x}px, ${y}px)`
      const start = { x: 360, y: 760 }
      const grab = { x: 406, y: 540 }
      const drop = { x: 1190, y: 566 }
      await anim(cursor, [{ opacity: 0, transform: at(start.x, start.y) }, { opacity: 1, transform: at(grab.x, grab.y) }], { duration: 700, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }).finished
      await sleep(200, id)
      anim(docx, [{ transform: 'scale(1)' }, { transform: 'scale(1.06)' }], { duration: 160 })
      await sleep(180, id)
      const dx = drop.x - grab.x
      const dy = drop.y - grab.y
      const move = { duration: 1300, easing: 'cubic-bezier(0.45, 0, 0.2, 1)' }
      anim(cursor, [{ transform: at(grab.x, grab.y) }, { transform: at(drop.x, drop.y) }], move)
      const fly = anim(docx, [{ transform: 'scale(1.06)' }, { transform: `translate(${dx}px, ${dy}px) scale(0.9)` }], move)
      await sleep(700, id)
      dragInto(frame, 'dragover')
      await fly.finished
      if (id !== runId) return
      await sleep(250, id)
      dragInto(frame, 'drop')
      anim(docx, [{ transform: `translate(${dx}px, ${dy}px) scale(0.9)`, opacity: 1 }, { transform: `translate(${dx}px, ${dy}px) scale(0.3)`, opacity: 0 }], { duration: 260, easing: 'ease-in' })
      anim(cursor, [{ opacity: 1 }, { opacity: 0 }], { duration: 300, delay: 300 })
      // the file is in: the four checks start on the left
      await sleep(400, id)
      el.querySelector('.checks')?.classList.add('show')
    },
  },
}

// ---------------------------------------------------------------- findings

/** One real finding per check in the Chinese demo report: the inspector
 *  row whose title and reference match is opened in the app. */
const FINDINGS = [
  { title: '未能在数据库中找到这篇文献', ref: '[70]' },
  { title: '被引文献与这条论断说的不是同一项工作', ref: '[40]' },
  { title: '建议修订：制 改为 置', ref: '' },
  { title: '参考文献构成偏离《电子学报》范文的常见范围', ref: '' },
]

function markLeaf(el: HTMLElement, n: number) {
  el.querySelectorAll('.lv').forEach((lv, k) => lv.classList.toggle('cur', k === n))
}

async function openFinding(frame: HTMLIFrameElement, f: { title: string; ref: string }, id: number) {
  const doc = frame.contentDocument
  if (!doc) return
  // back to the list first when a detail is open
  const back = doc.querySelector<HTMLElement>('.detail-in .link-accent')
  if (back) {
    back.click()
    await sleep(500, id)
  }
  const rows = Array.from(doc.querySelectorAll<HTMLElement>('.list-row'))
  const row = rows.find((r) => r.textContent?.includes(f.title) && r.textContent.includes(f.ref))
  row?.scrollIntoView({ block: 'center' })
  await sleep(250, id)
  row?.click()
}

// ---------------------------------------------------------------- app frame

function loadApp(frame: HTMLIFrameElement, state: string, id: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const onMsg = (e: MessageEvent) => {
      if (e.source !== frame.contentWindow || e.data?.clover !== 'ready') return
      removeEventListener('message', onMsg)
      if (id !== runId) reject(new Cancelled())
      else resolve()
    }
    addEventListener('message', onMsg)
    const params = `state=${state}&data=zh&t=${Date.now()}`
    if (APP_HTML) {
      // single-file deck: same document every time, parameters in the name
      frame.name = params
      frame.srcdoc = APP_HTML
    } else frame.src = `./app.html?${params}`
  })
}

/** A synthetic drag of the demo paper onto the app's home screen; the app
 *  handles it with its own drop handler, as if a file were dropped. */
function dragInto(frame: HTMLIFrameElement, type: 'dragover' | 'drop') {
  const w = frame.contentWindow as (Window & typeof globalThis) | null
  const doc = frame.contentDocument
  if (!w || !doc) return
  const dt = new w.DataTransfer()
  dt.items.add(new w.File(['clover'], 'paper.docx', {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  }))
  const target = doc.elementFromPoint(760, 400) ?? doc.body
  if (type === 'dragover') {
    target.dispatchEvent(new w.DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt }))
  }
  target.dispatchEvent(new w.DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }))
}

function drawChrome() {
  for (const c of document.querySelectorAll<HTMLElement>('.win-chrome')) {
    if (IS_WIN) {
      c.className = 'win-chrome win'
      c.innerHTML =
        '<svg viewBox="0 0 10 10"><path d="M0 5h10"/></svg>' +
        '<svg viewBox="0 0 10 10"><rect x="0.5" y="0.5" width="9" height="9"/></svg>' +
        '<svg viewBox="0 0 10 10"><path d="M0 0l10 10M10 0L0 10"/></svg>'
    } else {
      c.className = 'win-chrome mac'
      c.innerHTML = '<i></i><i></i><i></i>'
    }
  }
}
drawChrome()

// every content page carries the Clover mark and slogan at the bottom
for (const s of slides.filter((x) => x.classList.contains('framed'))) {
  const f = document.createElement('div')
  f.className = 'foot'
  f.innerHTML =
    `<img src="${logoUrl}" alt="">` +
    '<span class="foot-mark">Clover</span>' +
    '<span class="foot-line">投稿前的最后一公里，替你核对每一条引用</span>'
  s.appendChild(f)
}

// ---------------------------------------------------------------- navigation

let cur = -1
let stepNo = 0

function steps(el: HTMLElement) {
  return Number(el.dataset.steps ?? 1)
}

function run(p: Promise<void> | undefined) {
  p?.catch((e) => {
    if (!(e instanceof Cancelled)) console.error(e)
  })
}

function show(i: number) {
  i = Math.max(0, Math.min(slides.length - 1, i))
  slides.forEach((s, k) => {
    s.classList.toggle('on', k === i)
    for (const c of Array.from(s.classList)) if (c.startsWith('step-')) s.classList.remove(c)
  })
  cur = i
  stepNo = 0
  runId++
  const el = slides[i]
  run(hooks[el.dataset.title ?? '']?.enter?.(el, runId))
  history.replaceState(null, '', `#${i + 1}`)
  hud.textContent = `${i + 1} / ${slides.length}  ${el.dataset.title ?? ''}`
}

function next() {
  const el = slides[cur]
  if (stepNo + 1 < steps(el)) {
    stepNo++
    el.classList.add(`step-${stepNo}`)
    run(hooks[el.dataset.title ?? '']?.step?.(el, stepNo, runId))
  } else if (cur < slides.length - 1) show(cur + 1)
}

addEventListener('keydown', (e) => {
  if (['ArrowRight', 'PageDown', ' ', 'Enter'].includes(e.key)) next()
  else if (['ArrowLeft', 'PageUp'].includes(e.key)) show(cur - 1)
  else if (e.key === 'Home') show(0)
  else if (e.key === 'End') show(slides.length - 1)
  else if (e.key === 'r' || e.key === 'R') show(cur)
  else if (e.key === 'h' || e.key === 'H') hud.classList.toggle('show')
  else if (e.key === 'f' || e.key === 'F') {
    if (document.fullscreenElement) document.exitFullscreen()
    else document.documentElement.requestFullscreen()
  } else return
  e.preventDefault()
})
// clicks advance too, except inside the app window
deck.addEventListener('click', (e) => {
  if ((e.target as HTMLElement).closest('.win')) return
  next()
})
// the iframe takes keyboard focus when clicked; keep the keys on the deck
addEventListener('blur', () => setTimeout(() => window.focus(), 0))

show(Math.max(0, Number(location.hash.slice(1) || 1) - 1))

// ---------------------------------------------------------------- math

/** y of a CSS cubic-bezier at progress x (Newton on x(t)). */
function cubic(x1: number, y1: number, x2: number, y2: number, x: number) {
  const bx = (t: number) => 3 * x1 * t * (1 - t) ** 2 + 3 * x2 * t * t * (1 - t) + t ** 3
  const by = (t: number) => 3 * y1 * t * (1 - t) ** 2 + 3 * y2 * t * t * (1 - t) + t ** 3
  let t = x
  for (let k = 0; k < 8; k++) {
    const d = (bx(t + 1e-4) - bx(t)) / 1e-4
    if (!d) break
    t -= (bx(t) - x) / d
    t = Math.min(1, Math.max(0, t))
  }
  return by(t)
}
