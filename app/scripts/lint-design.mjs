// Design-lint: enforce AGENTS §6 mechanically.
// Fails on, anywhere under src/renderer (except styles/tokens.css):
//   - color literals (hex, rgb(), rgba()) — tokens.css is the only source
//   - border / outline (outside the :focus-visible rule) / text-decoration
//   - text-transform / uppercase / italic / letter-spacing in CSS or
//     className strings
//   - box-shadow / boxShadow values that don't go through --glass-* tokens
//   - any font-size other than 13/15/17/20/26/32 px
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
  /\boutline\b(?!-offset)/, // outline except in the allowed rule (checked below)
]
// border*/outline are banned as decoration; only 'none'/'0' resets pass
const BORDER_DECL = /\bborder(-(?!radius)\w+)?\s*:\s*['"]?([^;,}\n'"]*)/g
const FONT_OK = new Set(['13', '15', '17', '20', '26', '32'])

let failures = []

function scanFile(file) {
  const rel = path.relative(srcDir, file)
  if (rel === path.join('src', 'styles', 'tokens.css')) return
  const text = fs.readFileSync(file, 'utf-8')

  // color literals: hex and rgb()/rgba()
  for (const m of text.matchAll(/#[0-9a-fA-F]{3,8}\b/g)) {
    failures.push(`${file}: hex color literal ${m[0]}`)
  }
  for (const m of text.matchAll(/\brgba?\(/g)) {
    failures.push(`${file}: rgb()/rgba() literal '${m[0]}'`)
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
      // only the `outline:` declaration counts — `outline` is also a
      // legitimate identifier/comment word (the parsed-outline event)
      for (const m of text.matchAll(/\boutline\s*:[^;{]*;/g)) {
        if (inFocus(m.index)) continue
        failures.push(`${file}: outline usage '${m[0].trim()}'`)
      }
      continue
    }
    if (re.test(text)) failures.push(`${file}: banned pattern ${re}`)
  }
  for (const m of text.matchAll(BORDER_DECL)) {
    const v = m[2].trim()
    if (v !== 'none' && v !== '0') {
      failures.push(`${file}: border declaration '${m[0].trim()}'`)
    }
  }
  // shadows must come from --glass-* tokens, or be the single allowed
  // pane separator: a 1px hairline drawn with var(--separator)
  const SEPARATOR = /^(inset\s+)?-?1px\s+0\s+0\s+var\(--separator\)$|^0\s+-?1px\s+0\s+var\(--separator\)$/
  for (const m of text.matchAll(/\bbox-?[Ss]hadow\s*:\s*([^;,}\n]+)/g)) {
    const v = m[1].trim()
    if (v === 'none') continue
    if (!/var\(--glass-(edge|shadow)\)/.test(v) && !SEPARATOR.test(v)) {
      failures.push(`${file}: box-shadow without --glass token '${v}'`)
    }
  }
  // font-size values other than the 6-step scale
  for (const m of text.matchAll(/font-size:\s*([^;]+)/g)) {
    const v = m[1].trim()
    // the onboarding display title is the one sanctioned size off the scale
    if (v === 'var(--display-size)') continue
    if (!FONT_OK.has(v.replace('px', ''))) {
      failures.push(`${file}: font-size ${v}`)
    }
  }
  // inline-style fontSize in TSX (camelCase)
  for (const m of text.matchAll(/\bfontSize:\s*['"]?(\d+(?:\.\d+)?)px?['"]?/g)) {
    if (!FONT_OK.has(m[1])) {
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
