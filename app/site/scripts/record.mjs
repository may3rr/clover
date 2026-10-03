// Record tours of the web replica to video, one file per scene.
//
//   npm run site:record                       every tour, light, 2x, 30 fps
//   npm run site:record -- check support      only these tours
//   npm run site:record -- full --dark --fps 60 --frame
//   npm run site:record -- --page "index.html" --seconds 20
//
// Options
//   --dark            dark appearance           --scale <n>   pixel ratio (2)
//   --fps <n>         frame rate (30)           --frame       window on a desktop
//   --out <dir>       output dir (site-videos)  --page <path> record a page instead
//   --seconds <n>     length for --page (15)    --check       run tours, no video
//
// A vite dev server serves the site; Electron renders it offscreen and
// the frames go to ffmpeg (VideoToolbox when present). Tours live in
// site/src/replica/tour.ts.
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.resolve(here, '../..')
const argv = process.argv.slice(2)
const opt = (k, d) => {
  const i = argv.indexOf(`--${k}`)
  return i >= 0 ? argv[i + 1] : d
}
const flag = (k) => argv.includes(`--${k}`)
const valued = new Set(['--fps', '--scale', '--out', '--page', '--seconds'])
const names = argv.filter((a, i) => !a.startsWith('--') && !valued.has(argv[i - 1]))

const ALL = ['check', 'authenticity', 'support', 'distribution', 'norms', 'overview', 'export', 'settings', 'full']
const page = opt('page')
const jobs = page
  ? [{ name: path.basename(page).replace(/\W+/g, '-'), url: page, seconds: +opt('seconds', 15) }]
  : (names.length ? names : ALL).map((t) => ({
      name: t,
      url: `app.html?tour=${encodeURIComponent(t)}${flag('frame') ? '&frame=1' : ''}`,
    }))

const server = await createServer({
  configFile: path.join(appDir, 'site/vite.config.ts'),
  server: { port: 0 },
  logLevel: 'warn',
})
await server.listen()
const base = server.resolvedUrls.local[0]

const cfg = {
  base,
  jobs,
  out: path.resolve(appDir, opt('out', 'site-videos')),
  fps: +opt('fps', 30),
  scale: +opt('scale', 2),
  dark: flag('dark'),
  frame: flag('frame'),
  check: flag('check'),
}
if (!cfg.check) fs.mkdirSync(cfg.out, { recursive: true })

const electron = path.join(appDir, 'node_modules/.bin/electron')
const child = spawn(electron, [path.join(here, 'record-main.cjs')], {
  cwd: appDir,
  env: { ...process.env, CLOVER_RECORD: JSON.stringify(cfg) },
  stdio: 'inherit',
})
child.on('exit', async (code) => {
  await server.close()
  process.exit(code ?? 0)
})
