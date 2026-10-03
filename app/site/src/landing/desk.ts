import '../../../src/renderer/src/styles/tokens.css'
import '../replica/replica.css'
import './desk.css'

// the 1280:820 window, as large as the padding allows, centred
const PAD = 72
const h = 1080 - PAD * 2
const w = Math.round((h * 1280) / 820)
const slot = document.getElementById('slot')!
Object.assign(slot.style, {
  width: `${w}px`,
  height: `${h}px`,
  left: `${(1920 - w) / 2}px`,
  top: `${PAD}px`,
})
;(window as unknown as { __slot: object }).__slot = { x: (1920 - w) / 2, y: PAD, w, h, radius: 12 }
