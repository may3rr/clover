import '../../../src/renderer/src/styles/tokens.css'
import '../replica/replica.css'
import './desk.css'

// the 1280:820 window, as large as the padding allows, centred;
// ?cap=1 leaves a band under it for captions (site/scripts/promo.mjs)
const cap = new URLSearchParams(location.search).has('cap')
const PAD = cap ? 48 : 72
const h = 1080 - PAD - (cap ? 168 : PAD)
const w = Math.round((h * 1280) / 820)
const slot = document.getElementById('slot')!
Object.assign(slot.style, {
  width: `${w}px`,
  height: `${h}px`,
  left: `${(1920 - w) / 2}px`,
  top: `${PAD}px`,
})
;(window as unknown as { __slot: object }).__slot = { x: (1920 - w) / 2, y: PAD, w, h, radius: 12 }
