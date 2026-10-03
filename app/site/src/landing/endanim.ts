/** Closing animation for the video (index.html?card=end&anim=1).
 *
 *  Frame-exact: nothing moves on its own; site/scripts/endcard.mjs calls
 *  window.__render(t) for every frame and captures it. From the closing
 *  card, the Qwen mark in "Powered by 千问" starts turning, slowly at
 *  first and then faster, while it grows toward the centre until the
 *  screen is Qwen purple; the competition lines then rise in, in white. */

export const DURATION = 9

const HOLD = 0.8 // still closing card
const GROW = 3.6 // spin + zoom
const FILL = 0.5 // purple settles
const TEXT_AT = HOLD + GROW + FILL

// Qwen brand gradient (LobeHub qwen-color)
const PURPLE_A = '#6336E7'
const PURPLE_B = '#6F69F7'

const clamp = (x: number) => Math.min(1, Math.max(0, x))
const easeIn = (p: number) => p * p * p
const easeInOut = (p: number) => (p < 0.5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2)
const easeOut = (p: number) => 1 - (1 - p) ** 3

export async function setupEndAnim(): Promise<(t: number) => Promise<void>> {
  const src = document.querySelector<HTMLImageElement>('.hero-powered img')!
  const svgText = await fetch(src.src).then((r) => r.text())
  const r0 = src.getBoundingClientRect()

  // the spinning mark: inline SVG so it stays sharp at any size
  const spin = document.createElement('div')
  spin.innerHTML = svgText
  const svg = spin.querySelector('svg')!
  svg.setAttribute('width', '100%')
  svg.setAttribute('height', '100%')
  Object.assign(spin.style, {
    position: 'fixed',
    zIndex: '60',
    pointerEvents: 'none',
    visibility: 'hidden',
  })
  document.body.appendChild(spin)

  const wash = document.createElement('div')
  Object.assign(wash.style, {
    position: 'fixed',
    inset: '0',
    zIndex: '61',
    opacity: '0',
    background: `linear-gradient(135deg, ${PURPLE_A} 0%, ${PURPLE_B} 100%)`,
  })
  document.body.appendChild(wash)

  const card = document.createElement('div')
  card.className = 'end-card'
  card.innerHTML = `
    <p class="end-l end-event">天猫 AI 黑客松</p>
    <p class="end-l end-row"><span>参赛队伍</span>我要发顶刊</p>
    <p class="end-l end-row"><span>参赛赛道</span>效率进化</p>
    <p class="end-l end-row"><span>特别赛题</span>阿里云，基于 Qwen 的科研提效</p>`
  document.body.appendChild(card)
  const lines = Array.from(card.querySelectorAll<HTMLElement>('.end-l'))

  const W = innerWidth
  const H = innerHeight
  // The mark's solid core: a disc of radius 8.5% of its width centred at
  // (0.5, 0.494) (measured from the SVG). Zoom and turn about that point,
  // and end large enough that the core covers the half-diagonal.
  const FX = 0.5
  const FY = 0.494
  const END_SIZE = Math.hypot(W, H) / 2 / 0.075
  // LobeHub's colour mark is 84% opaque; ramp the moving copy to solid
  const stops = Array.from(svg.querySelectorAll('stop'))

  return async (t: number) => {
    const p = clamp((t - HOLD) / GROW)
    const moving = t > HOLD
    src.style.visibility = moving ? 'hidden' : 'visible'
    spin.style.visibility = moving ? 'visible' : 'hidden'

    // size: slow at first, then fast (ease-in), from the inline 28px
    const size = r0.width + (END_SIZE - r0.width) * easeIn(p)
    // centre drifts from the logo's place to the screen centre
    const c = easeInOut(p)
    const ax = r0.left + r0.width * FX
    const ay = r0.top + r0.height * FY
    const cx = ax + (W / 2 - ax) * c
    const cy = ay + (H / 2 - ay) * c
    // angle grows with t^3: angular speed rises from zero
    const angle = 900 * p * p * p
    Object.assign(spin.style, {
      width: `${size}px`,
      height: `${size}px`,
      left: `${cx - size * FX}px`,
      top: `${cy - size * FY}px`,
      transformOrigin: `${FX * 100}% ${FY * 100}%`,
      transform: `rotate(${angle}deg)`,
    })
    const op = String(0.84 + 0.16 * clamp(p / 0.2))
    stops.forEach((st) => st.setAttribute('stop-opacity', op))

    // purple wash closes the gaps between the mark's petals at the end
    wash.style.opacity = String(easeInOut(clamp((t - HOLD - GROW * 0.85) / (GROW * 0.15 + FILL))))

    lines.forEach((el, i) => {
      const k = easeOut(clamp((t - TEXT_AT - i * 0.28) / 0.7))
      el.style.opacity = String(k)
      el.style.transform = `translateY(${(1 - k) * 24}px)`
    })

    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
  }
}
