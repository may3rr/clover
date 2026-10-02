// Design-lint: enforce AGENTS §6 mechanically.
// Fails on, anywhere under src/renderer (except styles/tokens.css):
//   - hex color literals
//   - border / outline (outside the :focus-visible rule) / text-decoration
//   - text-transform / uppercase / italic / letter-spacing in CSS or
//     className strings
//   - any font-size other than 15px / 17px
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const srcDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../src/renderer'
)

const CSS_BANNED = [
  /\btext-decoration\b/i,
  /\btext-transform\b/i,
  /\buppercase\b/i,
  /\bitalic\b/i,
  /\bletter-spacing\b/i,
  /\bborder(-(?!radius)\w+)?\s*:/, // border*, except border-radius
  /\boutline\b(?!-offset)/, // outline except in the allowed rule (checked below)
]
const FONT_SIZE_OK = /\b(font-size:\s*)?(15px|17px)\b/

let failures = []

function scanFile(file) {
  const rel = path.relative(srcDir, file)
  if (rel === path.join('src', 'styles', 'tokens.css')) return
  const text = fs.readFileSync(file, 'utf-8')

  // hex colors
  for (const m of text.matchAll(/#[0-9a-fA-F]{3,8}\b/g)) {
    failures.push(`${file}: hex color literal ${m[0]}`)
  }
  // ranges of the allowed :focus-visible blocks (outline is legal inside)
  const focusRanges = []
  for (const m of text.matchAll(/:focus-visible\s*{[^}]*}/g)) {
    focusRanges.push([m.index, m.index + m[0].length])
  }
  const inFocus = (i) => focusRanges.some(([a, b]) => i >= a && i <= b)
  for (const re of CSS_BANNED) {
    // the :focus-visible outline rule is the only allowed outline
    if (re.source.includes('outline')) {
      for (const m of text.matchAll(/outline[^;{]*;/g)) {
        if (inFocus(m.index)) continue
        failures.push(`${file}: outline usage '${m[0].trim()}'`)
      }
      continue
    }
    if (re.test(text)) failures.push(`${file}: banned pattern ${re}`)
  }
  // font-size values other than 15px/17px
  for (const m of text.matchAll(/font-size:\s*([^;]+)/g)) {
    const v = m[1].trim()
    if (v !== '15px' && v !== '17px') {
      failures.push(`${file}: font-size ${v}`)
    }
  }
  // inline-style fontSize in TSX (camelCase)
  for (const m of text.matchAll(/\bfontSize:\s*['"]?(\d+(?:\.\d+)?)px?['"]?/g)) {
    if (m[1] !== '15' && m[1] !== '17') {
      failures.push(`${file}: fontSize ${m[0]}`)
    }
  }
  // tailwind text-* size utilities in classNames (text-sm, text-lg…)
  for (const m of text.matchAll(/\btext-(xs|sm|base|lg|xl|\dxl)\b/g)) {
    failures.push(`${file}: tailwind text size '${m[0]}'`)
  }
}

function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p)
    else if (/\.(tsx?|css|html)$/.test(e.name)) scanFile(p)
  }
}
walk(srcDir)

// whitelist: the single allowed outline lives in base.css :focus-visible
const baseCss = path.join(srcDir, 'src/styles/base.css')
const base = fs.readFileSync(baseCss, 'utf-8')
if (!/:focus-visible\s*{[^}]*outline:\s*2px solid var\(--accent\)/s.test(base)) {
  failures.push(`${baseCss}: missing required :focus-visible outline rule`)
}

if (failures.length) {
  console.error('lint:design failed:')
  for (const f of failures) console.error('  ' + f)
  process.exit(1)
}
console.log('lint:design ok')
