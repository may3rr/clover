// Put recordings into the landing-page frame: logo, tagline and download
// button on top, the recording as the app window below (3840 x 2160).
//
//   npm run site:frame                         render frames + composite every
//                                              mp4 under site-videos/01-* and 03-*
//   npm run site:frame -- a.mp4 b-dark.mp4     only these (*dark* -> dark frame)
//
// Output: site-videos/frame/ (frame-light.png, frame-dark.png, mask.png,
// slot.json) and site-videos/05-成片-主页框/<name>.mp4
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.resolve(here, '../..')
const videos = path.join(appDir, 'site-videos')
const frameDir = path.join(videos, 'frame')
const outDir = path.join(videos, '05-成片-主页框')
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
    env: { ...process.env, CLOVER_FRAME: JSON.stringify({ base: server.resolvedUrls.local[0], out: frameDir }) },
    stdio: ['ignore', 'inherit', 'ignore'],
  })
  c.on('exit', (code) => (code ? reject(new Error(`frame render exit ${code}`)) : resolve()))
})
await server.close()
const slot = JSON.parse(fs.readFileSync(path.join(frameDir, 'slot.json'), 'utf8'))

// 2. rounded-corner mask the size of the slot
const mask = path.join(frameDir, 'mask.png')
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${slot.w}" height="${slot.h}"><rect width="${slot.w}" height="${slot.h}" rx="${slot.radius}" fill="#fff"/></svg>`
spawnSync('rsvg-convert', ['-o', mask], { input: svg })

// 3. composite
const args = process.argv.slice(2)
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
    '-loop', '1', '-i', path.join(frameDir, `frame-${dark ? 'dark' : 'light'}.png`),
    '-i', src, '-i', mask,
    '-filter_complex', filter, '-r', '60', ...enc, '-movflags', '+faststart', dst,
  ], { stdio: 'inherit' })
  console.log(r.status === 0 ? path.relative(appDir, dst) : `failed: ${src}`)
}
