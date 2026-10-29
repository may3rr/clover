/** The real renderer on a static page: the mock preload/backend goes in
 *  first, then App mounts exactly as it does inside Electron.
 *
 *  app.html?state=<shot state>   open in a state from lib/shots.ts
 *  app.html?tour=<name>          play a tour (tour.ts) after load
 *  app.html?frame=1              draw the macOS window on a desktop, 1:1
 *                                (what site/scripts/record.mjs captures) */
import { go } from './mock'
import { marks, play, playFilm, reveal, TOURS } from './tour'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from '../../../src/renderer/src/App'
import '../../../src/renderer/src/styles/tokens.css'
import '../../../src/renderer/src/styles/base.css'
import './replica.css'

// the window is always "key" here — the inactive look is for real focus loss
document.hasFocus = () => true

// Inside a landing page window, scrollIntoView would scroll the page around
// the frame too; keep it to the nearest scroll container of the app.
if (window.parent !== window) {
  Element.prototype.scrollIntoView = function (arg?: boolean | ScrollIntoViewOptions) {
    const opt: ScrollIntoViewOptions = typeof arg === 'object' ? arg : { block: arg === false ? 'end' : 'start' }
    const block = opt.block ?? 'start'
    for (let p = this.parentElement; p; p = p.parentElement) {
      if (!/auto|scroll/.test(getComputedStyle(p).overflowY) || p.scrollHeight <= p.clientHeight) continue
      const r = this.getBoundingClientRect()
      const c = p.getBoundingClientRect()
      const top = r.top - c.top
      const bottom = top + r.height - c.height
      const d =
        block === 'center' ? top + r.height / 2 - c.height / 2
        : block === 'end' ? bottom
        : block === 'nearest' ? (top < 0 ? top : bottom > 0 ? Math.min(top, bottom) : 0)
        : top
      if (d) p.scrollBy({ top: d, behavior: opt.behavior })
      return
    }
  }
}

const q = new URLSearchParams(location.search)
const root = document.documentElement
if (q.get('frame')) root.classList.add('framed')
if (q.get('state')) root.classList.add('booting')

const clover = {
  go,
  play,
  reveal,
  tours: Object.keys(TOURS),
  marks,
  ready: false,
  tourDone: false,
}
declare global {
  interface Window {
    clover: typeof clover
  }
}
window.clover = clover

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

async function boot() {
  const state = q.get('state')
  if (state) await go(state)
  root.classList.remove('booting')
  clover.ready = true
  window.parent?.postMessage({ clover: 'ready' }, '*')
  const tour = q.get('tour')
  if (tour) {
    await new Promise((r) => setTimeout(r, Number(q.get('delay') ?? 600)))
    try {
      if (tour === 'film')
        await playFilm((q.get('durs') ?? '').split(',').map(Number))
      else await play(tour)
    } finally {
      clover.tourDone = true
      window.parent?.postMessage({ clover: 'tour-done', tour }, '*')
    }
  }
}
boot()
