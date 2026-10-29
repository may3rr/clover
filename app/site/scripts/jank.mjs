// Measure how the landing page scrolls, without anyone watching it.
//
//   npm run site:jank                       build, then measure -> label "latest"
//   npm run site:jank -- --label before     keep this run under a name
//   npm run site:jank -- --compare before   print this run next to an earlier one
//   npm run site:jank -- --dev              measure the dev server (no build;
//                                           React dev mode, slower than the site)
//
// A real (shown, inactive) Electron window gets scroll gestures:
//   page           flick through the whole page, pointer over the copy;
//                  frame drops and long frames
//   pageOverShots  the same with the pointer over the windows; also how
//                  many apps booted on the way (should be 0)
//   seam           a still and the live app it turns into on click, pixel
//                  diff, light and dark
//
// Output: site-videos/jank/<label>.json (+ seam PNGs when they differ)
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build, createServer, preview } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.resolve(here, '../..')
const configFile = path.join(appDir, 'site/vite.config.ts')
const out = path.join(appDir, 'site-videos/jank')
fs.mkdirSync(out, { recursive: true })

const argv = process.argv.slice(2)
const opt = (k) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : undefined)
const label = opt('--label') ?? 'latest'
const compare = opt('--compare')
const dev = argv.includes('--dev')

let server
if (dev) {
  server = await createServer({ configFile, server: { port: 0 }, logLevel: 'warn' })
  await server.listen()
} else {
  await build({ configFile, logLevel: 'warn' })
  server = await preview({ configFile, preview: { port: 0 }, logLevel: 'warn' })
}
const base = server.resolvedUrls.local[0]

const file = path.join(out, `${label}.json`)
await new Promise((resolve, reject) => {
  const c = spawn(path.join(appDir, 'node_modules/.bin/electron'), [path.join(here, 'jank-main.cjs')], {
    env: { ...process.env, CLOVER_JANK: JSON.stringify({ base, out, file }) },
    stdio: ['ignore', 'inherit', 'inherit'],
  })
  c.on('exit', (code) => (code ? reject(new Error(`jank exit ${code}`)) : resolve()))
})
if (dev) await server.close()
else await new Promise((r) => server.httpServer.close(r))

// ----------------------------------------------------------------- report
const now = JSON.parse(fs.readFileSync(file, 'utf8'))
const then = compare ? JSON.parse(fs.readFileSync(path.join(out, `${compare}.json`), 'utf8')) : null
const rows = [
  ['page: dropped frames %', (r) => r.page?.droppedPct],
  ['page: p95 frame ms', (r) => r.page?.p95],
  ['page: worst frame ms', (r) => r.page?.max],
  ['page: long frames > 50 ms', (r) => r.page?.longFrames],
  ['page: blocking ms', (r) => r.page?.blockingMs],
  ['over windows: dropped frames %', (r) => r.pageOverShots?.droppedPct],
  ['over windows: worst frame ms', (r) => r.pageOverShots?.max],
  ['over windows: apps booted', (r) => r.pageOverShots?.booted],
  ['seam light: pixels differing %', (r) => r.seam?.light?.diffPct],
  ['seam light: worst tile (0-255)', (r) => r.seam?.light?.worstTile],
  ['seam dark: pixels differing %', (r) => r.seam?.dark?.diffPct],
  ['seam dark: worst tile (0-255)', (r) => r.seam?.dark?.worstTile],
  ['seam: click -> live ms', (r) => r.seam?.light?.ms],
]
const fmt = (v) => (v === undefined || v === null ? '-' : typeof v === 'number' ? String(+v.toFixed(2)) : String(v))
const w = Math.max(...rows.map(([k]) => k.length))
console.log(`\n${'metric'.padEnd(w)}  ${then ? `${compare.padStart(10)}  ` : ''}${label.padStart(10)}`)
for (const [k, get] of rows)
  console.log(`${k.padEnd(w)}  ${then ? `${fmt(get(then)).padStart(10)}  ` : ''}${fmt(get(now)).padStart(10)}`)
console.log(`\n${path.relative(appDir, file)}`)
