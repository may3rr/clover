import '../../../src/renderer/src/styles/tokens.css'
import './landing.css'
import './frame.css'

// largest 1280:820 window that fits the space left under the copy
const slot = document.getElementById('slot')!
const top = slot.getBoundingClientRect().top
const h = Math.floor(1080 - top - 48)
const w = Math.round((h * 1280) / 820)
slot.style.width = `${w}px`
slot.style.height = `${h}px`
const r = slot.getBoundingClientRect()
;(window as unknown as { __slot: object }).__slot = {
  x: r.left,
  y: r.top,
  w: r.width,
  h: r.height,
  radius: 12,
}
