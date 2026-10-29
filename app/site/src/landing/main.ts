import '../../../src/renderer/src/styles/tokens.css'
import './landing.css'
import { LINKS } from './links'
import { startField } from './field'
import { renderDoc } from './doc'

type CloverWin = Window & {
  clover?: {
    go(s: string): Promise<void>
    play(t: string): Promise<void>
    reveal(sel: string, ms?: number): Promise<void>
  }
}

// ------------------------------------------------------- ?card=end
// closing card of the video: the first screen plus "Powered by 千问"
// (Qwen mark from LobeHub lobe-icons, MIT)
if (new URLSearchParams(location.search).get('card') === 'end') {
  document.querySelector('.hero-team')?.insertAdjacentHTML(
    'afterend',
    `<p class="hero-powered"><span>Powered by</span><img src="./brand/qwen-color.svg" alt="" width="28" height="28" /><b>千问</b></p>`
  )
  // &anim=1: frame-exact closing animation, driven by site/scripts/endcard.mjs
  if (new URLSearchParams(location.search).get('anim')) {
    const w = window as unknown as {
      __endSetup: () => Promise<number>
      __render?: (t: number) => Promise<void>
    }
    w.__endSetup = async () => {
      const { setupEndAnim, DURATION } = await import('./endanim')
      w.__render = await setupEndAnim()
      return DURATION
    }
  }
}

// ---------------------------------------------------------------- links
for (const a of document.querySelectorAll<HTMLAnchorElement>('[data-link]')) {
  const href = LINKS[a.dataset.link as keyof typeof LINKS]
  if (href) a.href = href
  if (a.dataset.link !== 'mac') a.target = '_blank'
}

// ------------------------------------------------------------------ nav
const nav = document.getElementById('nav')!
const onScroll = () => nav.classList.toggle('solid', scrollY > 8)
addEventListener('scroll', onScroll, { passive: true })
onScroll()

// -------------------------------------------------------------- windows
/** Each .window hosts the real app (app.html) at its native 1280 x 820,
 *  scaled to the box. Off-screen ones load when they get close. */
const frames = new Map<Element, HTMLIFrameElement>()
/** apps that have booted (a still also marks its window .ready) */
const booted = new Set<Element>()
const readyWaiters = new Map<HTMLIFrameElement, (() => void)[]>()

function mount(box: HTMLElement) {
  if (frames.has(box)) return
  const f = document.createElement('iframe')
  f.src = box.dataset.src!
  f.title = 'Clover 界面'
  f.setAttribute('scrolling', 'no')
  box.appendChild(f)
  frames.set(box, f)
}
const sizer = new ResizeObserver((entries) => {
  for (const e of entries) {
    const box = e.target as HTMLElement
    box.style.setProperty('--s', String(box.clientWidth / 1280))
  }
})
const lazy = new IntersectionObserver(
  (entries) => {
    for (const e of entries)
      if (e.isIntersecting) {
        mount(e.target as HTMLElement)
        lazy.unobserve(e.target)
      }
  },
  { rootMargin: '800px 0px' }
)
for (const box of document.querySelectorAll<HTMLElement>('.window')) {
  sizer.observe(box)
  if (box.hasAttribute('data-manual')) continue
  if (box.hasAttribute('data-eager')) mount(box)
  else lazy.observe(box)
}

addEventListener('message', (e) => {
  if (e.data?.clover !== 'ready') return
  for (const [box, f] of frames)
    if (f.contentWindow === e.source) {
      box.classList.add('ready')
      booted.add(box)
      readyWaiters.get(f)?.forEach((fn) => fn())
      readyWaiters.delete(f)
    }
})

/** The replica's driver, once that window has booted. */
async function driver(box: HTMLElement) {
  mount(box)
  const f = frames.get(box)!
  if (!booted.has(box))
    await new Promise<void>((r) => readyWaiters.set(f, [...(readyWaiters.get(f) ?? []), r]))
  return (f.contentWindow as CloverWin).clover!
}

// ------------------------------------------------------- the check replay
const checkBox = document.getElementById('check-window')!
const replay = document.getElementById('replay') as HTMLButtonElement
let playing = false
async function playCheck() {
  if (playing) return
  playing = true
  replay.disabled = true
  try {
    const c = await driver(checkBox)
    await c.play('check')
  } finally {
    playing = false
    replay.disabled = false
  }
}
replay.addEventListener('click', playCheck)
new IntersectionObserver(
  (entries, obs) => {
    if (entries.some((e) => e.isIntersecting)) {
      obs.disconnect()
      playCheck()
    }
  },
  { threshold: 0.6 }
).observe(checkBox)

// ----------------------------------------------------- four layers
// Each window is a still of the app (site/public/stills, made by
// npm run site:stills from the replica itself). A click boots the live app
// behind the still, drives it to the same state and lets it settle, then
// fades the still out over identical pixels.

/** wait until the app inside the frame has stopped animating */
async function settle(f: HTMLIFrameElement) {
  const w = f.contentWindow!
  const frame = () => new Promise((r) => w.requestAnimationFrame(r))
  for (let quiet = 0, i = 0; quiet < 3 && i < 120; i++) {
    await frame()
    quiet = w.document.getAnimations().length ? 0 : quiet + 1
  }
}

for (const box of document.querySelectorAll<HTMLElement>('.window[data-still]')) {
  const { still, state, reveal } = box.dataset
  const pic = document.createElement('picture')
  pic.className = 'still on'
  pic.innerHTML =
    `<source media="(prefers-color-scheme: dark)" srcset="./stills/${still}-dark.webp" />` +
    `<img src="./stills/${still}-light.webp" alt="" decoding="async" loading="lazy" />`
  box.appendChild(pic)
  box.dataset.mode = 'still'
  const img = pic.querySelector('img')!
  const shown = () => box.classList.add('ready')
  if (img.complete) shown()
  else img.addEventListener('load', shown, { once: true })

  box.dataset.src = `app.html?state=${encodeURIComponent(state!)}`
  // boot once the pointer rests on it, so a click only has to settle it;
  // windows that merely pass under the pointer while scrolling stay stills
  let rest = 0
  const cancel = () => clearTimeout(rest)
  box.addEventListener('pointerenter', () => (cancel(), (rest = window.setTimeout(() => mount(box), 400))))
  box.addEventListener('pointerleave', cancel)
  addEventListener('scroll', cancel, { passive: true })
  let going = false
  box.addEventListener('click', async () => {
    if (going || box.dataset.mode === 'live') return
    going = true
    try {
      const c = await driver(box)
      if (reveal) await c.reveal(reveal, 0)
      await settle(frames.get(box)!)
      box.dataset.mode = 'live'
      pic.classList.remove('on')
    } finally {
      going = false
    }
  })
}

// --------------------------------------------------------------- reveal
const revealObs = new IntersectionObserver(
  (entries) => {
    for (const e of entries)
      if (e.isIntersecting) {
        e.target.classList.add('in')
        revealObs.unobserve(e.target)
      }
  },
  { rootMargin: '0px 0px -12% 0px' }
)
for (const el of document.querySelectorAll('.band, .about, .principles .grid > div, .cta, .doc'))
  el.classList.add('reveal'), revealObs.observe(el)

// ----------------------------------------------------- export + footer
renderDoc(document.getElementById('doc')!)
startField(document.getElementById('field') as HTMLCanvasElement)

// ------------------------------------------------- ?autoscroll=<seconds>
// a steady top-to-bottom pass for recording the page itself
// (npm run site:record -- --page "index.html?autoscroll=40" --seconds 44)
const auto = Number(new URLSearchParams(location.search).get('autoscroll'))
if (auto > 0) {
  document.documentElement.style.scrollBehavior = 'auto'
  setTimeout(() => {
    const t0 = performance.now()
    const total = document.documentElement.scrollHeight - innerHeight
    const ease = (x: number) => (x < 0.5 ? 2 * x * x : 1 - (-2 * x + 2) ** 2 / 2)
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / (auto * 1000))
      scrollTo(0, ease(k) * total)
      if (k < 1) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }, 1500)
}
