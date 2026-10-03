// Clover app icon — generates build/icon.svg (1024 canvas, macOS grid).
// Four geometric hearts in the layer hues (authenticity indigo, support
// blue, distribution teal, norms purple) and a trail of three dots: the
// last mile, and the citation markers the skeleton page lights up.
//   node site/scripts/icon.mjs  ->  build/icon.svg (+ public/icon.svg)
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const r = (n) => Math.round(n * 10) / 10

const CX = 494, CY = 486   // clover centre
const A = 96               // half-diagonal of each heart's square
const G = 13               // gap between leaves
const LEAVES = [
  // [direction deg, top colour, bottom colour]
  [-90, '#6e6cf0', '#5856d6'],  // up    authenticity
  [0, '#2b93ff', '#007aff'],    // right support
  [90, '#4cc6dc', '#2aa5bb'],   // down  distribution
  [180, '#c06cf0', '#a548d6'],  // left  norms
]

// heart pointing along +x with its tip at (G, 0): a square rotated 45°
// plus two circles on its outer edges
function heart() {
  const s = A, c = A / Math.SQRT2
  const tip = [G, 0], top = [G + s, -s], far = [G + 2 * s, 0], bot = [G + s, s]
  // outline: tip -> top corner, arc over upper lobe to far corner, arc over
  // lower lobe to bottom corner, back to tip
  return `M${tip} L${top} A${r(c)} ${r(c)} 0 0 1 ${far} A${r(c)} ${r(c)} 0 0 1 ${bot} Z`
}

const dots = [
  [262, 27],
  [326, 20],
  [382, 14],
].map(([d, rad]) => [CX + d / Math.SQRT2, CY + d / Math.SQRT2, rad])

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="paper" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff"/>
      <stop offset="1" stop-color="#efeee9"/>
    </linearGradient>
    <filter id="drop" x="-10%" y="-10%" width="120%" height="125%">
      <feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#000" flood-opacity="0.18"/>
    </filter>
    <filter id="soft" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#37352f" flood-opacity="0.16"/>
    </filter>
${LEAVES.map(([deg, a, b], i) => {
  // gradient runs top->bottom on screen whatever the leaf's direction
  return `    <linearGradient id="l${i}" gradientUnits="userSpaceOnUse" x1="0" y1="${CY - 290}" x2="0" y2="${CY + 290}">
      <stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/>
    </linearGradient>`
}).join('\n')}
  </defs>
  <rect x="100" y="100" width="824" height="824" rx="185" fill="url(#paper)" filter="url(#drop)"/>
  <g filter="url(#soft)">
${LEAVES.map(([deg], i) => `    <path d="${heart()}" fill="url(#l${i})" transform="translate(${CX} ${CY}) rotate(${deg})"/>`).join('\n')}
${dots.map(([x, y, rad]) => `    <circle cx="${r(x)}" cy="${r(y)}" r="${rad}" fill="#37352f"/>`).join('\n')}
  </g>
</svg>
`
// gradients are in user space, so rotate them back: simplest is to emit
// each leaf already rotated — apply the rotation to path points instead
function rotated(deg) {
  const t = (deg * Math.PI) / 180, cos = Math.cos(t), sin = Math.sin(t)
  return heart().replace(/(-?[\d.]+),(-?[\d.]+)/g, (_, x, y) => {
    const X = +x, Y = +y
    return `${r(CX + X * cos - Y * sin)},${r(CY + X * sin + Y * cos)}`
  })
}
const out = svg.replace(
  /<path d="[^"]+" fill="url\(#l(\d)\)" transform="[^"]+"\/>/g,
  (_, i) => `<path d="${rotated(LEAVES[+i][0])}" fill="url(#l${i})"/>`
)
fs.writeFileSync(path.join(appDir, 'build/icon.svg'), out)
fs.mkdirSync(path.join(appDir, 'site/public'), { recursive: true })
fs.writeFileSync(path.join(appDir, 'site/public/icon.svg'), out)
console.log('build/icon.svg, site/public/icon.svg')

// social preview card (1200 x 630) for og:image
const inner = out.replace(/^<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '')
const og = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#ffffff"/>
  <g transform="translate(456 64) scale(0.28)">${inner}</g>
  <text x="600" y="430" text-anchor="middle" font-family="SF Pro Display, Helvetica Neue, Helvetica, Arial, sans-serif" font-size="64" font-weight="700" letter-spacing="-2" fill="#37352f">The last mile of the paper</text>
  <text x="600" y="500" text-anchor="middle" font-family="PingFang SC, Hiragino Sans GB, sans-serif" font-size="30" font-weight="500" fill="#37352f" fill-opacity="0.65" letter-spacing="2">投稿的最后一公里</text>
</svg>
`
fs.writeFileSync(path.join(appDir, 'site/scripts/.og.svg'), og)
