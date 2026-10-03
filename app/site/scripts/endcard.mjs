// Closing animation, rendered frame by frame (no real-time capture, so 4K
// at 60 fps stays smooth): index.html?card=end&anim=1 exposes __render(t).
//   npm run site:endcard  ->  site-videos/frame/end-anim.mp4 (3840 x 2160)
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.resolve(here, '../..')
const server = await createServer({ configFile: path.join(appDir, 'site/vite.config.ts'), server: { port: 0 }, logLevel: 'warn' })
await server.listen()
const out = path.join(appDir, 'site-videos/frame/end-anim.mp4')
await new Promise((resolve, reject) => {
  const c = spawn(path.join(appDir, 'node_modules/.bin/electron'), [path.join(here, 'endcard-main.cjs')], {
    env: { ...process.env, CLOVER_END: JSON.stringify({ url: server.resolvedUrls.local[0] + 'index.html?card=end&anim=1', out, fps: 60 }) },
    stdio: ['ignore', 'inherit', 'ignore'],
  })
  c.on('exit', (code) => (code ? reject(new Error(`exit ${code}`)) : resolve()))
})
await server.close()
console.log(path.relative(appDir, out))
