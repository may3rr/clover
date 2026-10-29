// Stills of the app windows in the "four layers" section.
//
//   npm run site:stills
//
// Every window in index.html with data-still names a still and the app
// state it shows (data-state, plus data-reveal when the reading area scrolls
// to an element). Each is rendered by the replica itself at 1280 x 820, 2x, light
// and dark, then written as site/public/stills/<still>-<theme>.webp at the
// width the page ever draws it, so the live app that replaces a still on
// click lands on the same pixels. Re-run after any change to the renderer.
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.resolve(here, '../..')
const outDir = path.join(appDir, 'site/public/stills')
const WIDTH = 1600 // widest a window gets (753 CSS px) at 2x, rounded up

const html = fs.readFileSync(path.join(appDir, 'site/index.html'), 'utf8')
const attr = (tag, k) => tag.match(new RegExp(`data-${k}=(?:"([^"]*)"|'([^']*)')`))?.slice(1).find(Boolean)
const shots = [...html.matchAll(/<div class="window" data-still[^>]*>/g)].map(([tag]) => ({
  name: attr(tag, 'still'),
  state: attr(tag, 'state'),
  reveal: attr(tag, 'reveal'),
}))
if (!shots.length || shots.some((s) => !s.name || !s.state)) throw new Error('every data-still window needs data-state')

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'clover-stills-'))
const server = await createServer({
  configFile: path.join(appDir, 'site/vite.config.ts'),
  server: { port: 0 },
  logLevel: 'warn',
})
await server.listen()
await new Promise((resolve, reject) => {
  const c = spawn(path.join(appDir, 'node_modules/.bin/electron'), [path.join(here, 'stills-main.cjs')], {
    env: { ...process.env, CLOVER_STILLS: JSON.stringify({ base: server.resolvedUrls.local[0], out: tmp, shots }) },
    stdio: ['ignore', 'inherit', 'ignore'],
  })
  c.on('exit', (code) => (code ? reject(new Error(`stills exit ${code}`)) : resolve()))
})
await server.close()

fs.mkdirSync(outDir, { recursive: true })
for (const f of fs.readdirSync(tmp).filter((f) => f.endsWith('.png'))) {
  const dst = path.join(outDir, f.replace(/\.png$/, '.webp'))
  const r = spawnSync('cwebp', ['-quiet', '-q', '92', '-resize', String(WIDTH), '0', path.join(tmp, f), '-o', dst])
  if (r.status !== 0) throw new Error(`cwebp failed on ${f}`)
  console.log(`${path.relative(appDir, dst)}  ${Math.round(fs.statSync(dst).size / 1024)} KB`)
}
fs.rmSync(tmp, { recursive: true })
