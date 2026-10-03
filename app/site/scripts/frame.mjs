// Put recordings into a backdrop at 3840 x 2160.
//
//   npm run site:frame                         landing frame, every mp4 under
//                                              site-videos/01-* and 03-*
//   npm run site:frame -- a.mp4 b-dark.mp4     only these (*dark* -> dark frame)
//   --template frame   logo, tagline and download button on top (frame.html)
//   --template desk    the window on a desktop, padding all round (desk.html)
//   --template cover   no video: the landing page's first screen as a PNG
//
// Output: site-videos/frame/<template>-{light,dark}.png, <template>.slot.json,
// <template>.mask.png; videos in site-videos/05-成片-<主页框|桌面>/<name>.mp4
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.resolve(here, '../..')
const videos = path.join(appDir, 'site-videos')
const argv = process.argv.slice(2)
const ti = argv.indexOf('--template')
const template = ti >= 0 ? argv[ti + 1] : 'frame'
const TEMPLATES = {
  frame: { page: 'frame.html', dir: '05-成片-主页框' },
  desk: { page: 'desk.html', dir: '05-成片-桌面' },
  cover: { page: 'index.html', ready: '.hero-window .window.ready' },
}
const T = TEMPLATES[template]
if (!T) throw new Error(`unknown template ${template}`)
const frameDir = path.join(videos, 'frame')
const outDir = path.join(videos, T.dir ?? 'frame')
fs.mkdirSync(frameDir, { recursive: true })
fs.mkdirSync(outDir, { recursive: true })

// 1. render the frames
const server = await createServer({
  configFile: path.join(appDir, 'site/vite.config.ts'),
  server: { port: 0 },
  logLevel: 'warn',
})
await server.listen()
await new Promise((resolve, reject) => {
  const c = spawn(path.join(appDir, 'node_modules/.bin/electron'), [path.join(here, 'frame-main.cjs')], {
    env: {
      ...process.env,
      CLOVER_FRAME: JSON.stringify({
        base: server.resolvedUrls.local[0], out: frameDir, page: T.page, name: template,
        ready: T.ready, themes: ['light', 'dark'],
      }),
    },
    stdio: ['ignore', 'inherit', 'ignore'],
  })
  c.on('exit', (code) => (code ? reject(new Error(`frame render exit ${code}`)) : resolve()))
})
await server.close()
if (!T.dir) {
  console.log(`site-videos/frame/${template}-light.png, ${template}-dark.png`)
  process.exit(0)
}
const slot = JSON.parse(fs.readFileSync(path.join(frameDir, `${template}.slot.json`), 'utf8'))

// 2. rounded-corner mask the size of the slot
const mask = path.join(frameDir, `${template}.mask.png`)
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${slot.w}" height="${slot.h}"><rect width="${slot.w}" height="${slot.h}" rx="${slot.radius}" fill="#fff"/></svg>`
spawnSync('rsvg-convert', ['-o', mask], { input: svg })

// 3. composite
const args = argv.filter((a, i) => a !== '--template' && argv[i - 1] !== '--template')
const inputs = args.length
  ? args.map((a) => path.resolve(a))
  : fs.readdirSync(videos)
      .filter((d) => /^0[13]-/.test(d))
      .flatMap((d) => fs.readdirSync(path.join(videos, d)).filter((f) => f.endsWith('.mp4')).map((f) => path.join(videos, d, f)))
const vt = /h264_videotoolbox/.test(spawnSync('ffmpeg', ['-hide_banner', '-encoders'], { encoding: 'utf8' }).stdout)
for (const src of inputs) {
  const dark = /dark|深色/.test(src)
  const name = path.basename(src, '.mp4') + (dark && !/dark/.test(path.basename(src)) ? '-dark' : '')
  const dst = path.join(outDir, `${name}.mp4`)
  const filter =
    `[1:v]scale=${slot.w}:${slot.h}:flags=lanczos,format=rgba[v];` +
    `[2:v]format=rgba,alphaextract[m];[v][m]alphamerge[vm];` +
    `[0:v][vm]overlay=${slot.x}:${slot.y}:shortest=1,format=yuv420p`
  const enc = vt ? ['-c:v', 'h264_videotoolbox', '-b:v', '45M'] : ['-c:v', 'libx264', '-preset', 'medium', '-crf', '16']
  const r = spawnSync('ffmpeg', [
    '-y', '-loglevel', 'error',
    '-loop', '1', '-i', path.join(frameDir, `${template}-${dark ? 'dark' : 'light'}.png`),
    '-i', src, '-i', mask,
    '-filter_complex', filter, '-r', '60', ...enc, '-movflags', '+faststart', dst,
  ], { stdio: 'inherit' })
  console.log(r.status === 0 ? path.relative(appDir, dst) : `failed: ${src}`)
}
