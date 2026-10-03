import '../../../src/renderer/src/styles/tokens.css'
import './landing.css'
import { LINKS } from './links'
import { startField } from './field'
import { renderDoc } from './doc'

type CloverWin = Window & {
  clover?: { go(s: string): Promise<void>; play(t: string): Promise<void> }
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
  if (box.hasAttribute('data-eager')) mount(box)
  else lazy.observe(box)
}

addEventListener('message', (e) => {
  if (e.data?.clover !== 'ready') return
  for (const [box, f] of frames)
    if (f.contentWindow === e.source) {
      box.classList.add('ready')
      readyWaiters.get(f)?.forEach((fn) => fn())
      readyWaiters.delete(f)
    }
})

/** The replica's driver, once that window has booted. */
async function driver(box: HTMLElement) {
  mount(box)
  const f = frames.get(box)!
  if (!box.classList.contains('ready'))
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

// ----------------------------------------------- four layers, sticky stage
const stage = document.querySelector<HTMLElement>('.stage')!
const layersBox = document.getElementById('layers-window')!
const steps = Array.from(document.querySelectorAll<HTMLElement>('.step'))
let current = ''
let pending: string | null = null
async function show(state: string) {
  pending = state
  const c = await driver(layersBox)
  // a fast scroll queues several states; only the last one matters
  while (pending && pending !== current) {
    const next: string = pending
    current = next
    await c.go(next)
  }
}
const stepObs = new IntersectionObserver(
  (entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue
      steps.forEach((s) => s.classList.toggle('on', s === e.target))
      show((e.target as HTMLElement).dataset.state!)
    }
  },
  { rootMargin: '-45% 0px -45% 0px' }
)
steps.forEach((s) => stepObs.observe(s))
steps[0].classList.add('on')

function centerStage() {
  if (matchMedia('(max-width: 960px)').matches) {
    stage.style.top = ''
    return
  }
  stage.style.top = `${Math.max(72, (innerHeight - stage.offsetHeight) / 2)}px`
}
new ResizeObserver(centerStage).observe(stage)
addEventListener('resize', centerStage)

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
for (const el of document.querySelectorAll('.band, .principles .grid > div, .cta, .doc'))
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
