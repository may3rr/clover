// Electron side of jank.mjs: a real window, synthetic trackpad input, numbers
// out. Frames are timed with requestAnimationFrame in the page; long frames
// come from the long-animation-frame observer.
const { app, BrowserWindow, nativeTheme, nativeImage } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const { base, out, file } = JSON.parse(process.env.CLOVER_JANK)
app.dock?.hide()
app.on('window-all-closed', () => {})
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
setTimeout(() => {
  console.error('jank: timed out')
  app.exit(1)
}, 300_000)

const W = 1440
const H = 900
const TEXT = { x: 320, y: H / 2 } // pointer over the copy column
const SHOTS = { x: 1000, y: H / 2 } // pointer over the window column
let wc
let gain = 1 // wheel px -> scrolled CSS px, calibrated at start

// page-side recorder: frame times and long animation frames
const RECORDER = `(() => {
  const frames = [], loaf = []
  let rec = false
  new PerformanceObserver((l) => {
    if (rec) for (const e of l.getEntries())
      loaf.push({ d: e.duration, b: e.blockingDuration ?? 0 })
  }).observe({ type: 'long-animation-frame' })
  const loop = (t) => {
    if (rec) frames.push(t)
    requestAnimationFrame(loop)
  }
  requestAnimationFrame(loop)
  const shots = [...document.querySelectorAll('.window[data-still]')]
  window.__jank = {
    start() { frames.length = 0; loaf.length = 0; rec = true },
    stop() { rec = false; return { frames: frames.slice(), loaf: loaf.slice() } },
    center(i) {
      const r = shots[i].getBoundingClientRect()
      scrollTo({ top: scrollY + r.top + r.height / 2 - innerHeight / 2, behavior: 'instant' })
    },
    rect(i) {
      const r = shots[i].getBoundingClientRect()
      return { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) }
    },
    shots: () => shots.length,
    live: (i) => shots[i].dataset.mode === 'live',
    booted: () => shots.filter((b) => b.querySelector('iframe')).length,
    end: () => scrollY + innerHeight >= document.documentElement.scrollHeight - 2,
  }
})()`
const js = (s) => wc.executeJavaScript(s)

/** One flick, `dy` CSS px in total (positive = down the page), sent as a
 *  single scroll gesture (begin, updates, end) through the DevTools
 *  protocol. Plain wheel events carry no gesture phase, so the browser
 *  sees each as its own scroll and scroll-snap-stop never applies.
 *  `n` sets the speed: the distance spread over n frames. */
async function flick(dy, at = TEXT, n = 40) {
  wc.sendInputEvent({ type: 'mouseMove', x: at.x, y: at.y })
  const dist = dy / gain
  await wc.debugger.sendCommand('Input.synthesizeScrollGesture', {
    x: at.x, y: at.y, xDistance: 0, yDistance: -Math.round(dist),
    speed: Math.round(Math.abs(dist) / (n * 0.016)),
    gestureSourceType: 'mouse', preventFling: false,
  })
}

function frameStats({ frames, loaf }) {
  const dts = []
  for (let i = 1; i < frames.length; i++) dts.push(frames[i] - frames[i - 1])
  const sorted = [...dts].sort((a, b) => a - b)
  const q = (p) => sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] ?? 0
  const interval = q(0.5) || 16.7
  let dropped = 0
  let expected = 0
  for (const dt of dts) {
    const k = Math.max(1, Math.round(dt / interval))
    expected += k
    dropped += k - 1
  }
  const long = loaf.filter((e) => e.d > 50)
  return {
    refreshMs: +interval.toFixed(2),
    droppedPct: expected ? (100 * dropped) / expected : 0,
    p95: q(0.95),
    max: sorted[sorted.length - 1] ?? 0,
    longFrames: long.length,
    blockingMs: Math.round(loaf.reduce((s, e) => s + e.b, 0)),
  }
}

async function capture(rect) {
  const img = await wc.capturePage(rect)
  return img
}

/** Still vs live. Text antialiasing differs between a resampled image and
 *  an iframe rasterised at its scale, so compare at quarter size (edges
 *  average out, a moved or missing element does not) and also report the
 *  worst 16 px tile at full size (mean channel difference, 0-255). */
function diff(a, b) {
  const { width, height } = a.getSize()
  const B0 = b.resize({ width, height })
  const A = a.toBitmap()
  const B = B0.toBitmap()
  let worst = 0
  let tile = null
  for (let ty = 0; ty + 16 <= height; ty += 16)
    for (let tx = 0; tx + 16 <= width; tx += 16) {
      let sum = 0
      for (let y = ty; y < ty + 16; y++)
        for (let x = tx; x < tx + 16; x++) {
          const i = (y * width + x) * 4
          sum += Math.abs(A[i] - B[i]) + Math.abs(A[i + 1] - B[i + 1]) + Math.abs(A[i + 2] - B[i + 2])
        }
      const m = sum / (16 * 16 * 3)
      if (m > worst) (worst = m), (tile = { x: tx, y: ty, of: `${width}x${height}` })
    }
  const q = { width: Math.round(width / 4), height: Math.round(height / 4), quality: 'best' }
  const qa = a.resize(q).toBitmap()
  const qb = B0.resize(q).toBitmap()
  const mask = Buffer.alloc(qa.length)
  let n = 0
  for (let i = 0; i < qa.length; i += 4) {
    const d = Math.max(Math.abs(qa[i] - qb[i]), Math.abs(qa[i + 1] - qb[i + 1]), Math.abs(qa[i + 2] - qb[i + 2]))
    if (d > 24) (n++, (mask[i + 2] = 255))
    mask[i + 3] = 255
  }
  return {
    diffPct: (100 * n) / (q.width * q.height),
    worstTile: +worst.toFixed(1),
    tile,
    mask: nativeImage.createFromBitmap(mask, { width: q.width, height: q.height }),
  }
}

app.whenReady().then(async () => {
  nativeTheme.themeSource = 'light'
  const win = new BrowserWindow({
    width: W, height: H, useContentSize: true, show: false,
    // own in-memory session: the record scripts leave a 2x zoom on localhost
    webPreferences: { backgroundThrottling: false, partition: 'jank', zoomFactor: 1 },
  })
  wc = win.webContents
  wc.debugger.attach('1.3')
  const errors = []
  wc.on('console-message', (e) => {
    if (e.level === 'error' || e.level === 3) errors.push(e.message)
  })
  await win.loadURL(base + 'index.html')
  wc.setZoomFactor(1)
  win.showInactive()
  for (let i = 0; i < 200; i++) {
    if (await js(`!!document.querySelector('.hero-window .window.ready')`)) break
    await sleep(100)
  }
  await js(RECORDER)
  await sleep(1000)
  const result = {
    when: new Date().toISOString(),
    viewport: await js('[innerWidth, innerHeight, devicePixelRatio]'),
  }
  // calibrate: how far does a flick of 600 actually go
  await js(`scrollTo({ top: 0, behavior: 'instant' })`)
  await sleep(500)
  await flick(600)
  await sleep(1200)
  gain = (await js('scrollY')) / 600
  result.gain = gain

  // ---------------------------------------------------------------- page
  // top to bottom twice: pointer over the copy, then over the windows
  // (passing over a still must not boot the app behind it)
  for (const [name, at] of [['page', TEXT], ['pageOverShots', SHOTS]]) {
    await js(`scrollTo({ top: 0, behavior: 'instant' })`)
    await sleep(800)
    await js('__jank.start()')
    for (let i = 0; i < 60 && !(await js('__jank.end()')); i++) {
      await flick(700, at)
      await sleep(500)
    }
    result[name] = frameStats(await js('__jank.stop()'))
  }
  result.pageOverShots.booted = await js('__jank.booted()')

  // ---------------------------------------------------------------- seam
  // still vs the live app it turns into; a fresh window per theme
  result.seam = {}
  for (const [theme, i] of [['light', 1], ['dark', 3]]) {
    nativeTheme.themeSource = theme
    await js(`__jank.center(${i})`)
    await sleep(2000)
    const r = await js(`__jank.rect(${i})`)
    wc.sendInputEvent({ type: 'mouseMove', x: TEXT.x, y: TEXT.y })
    await sleep(400)
    const a = await capture(r)
    const at = { x: r.x + Math.round(r.width * 0.55), y: r.y + Math.round(r.height * 0.5) }
    wc.sendInputEvent({ type: 'mouseMove', ...at })
    wc.sendInputEvent({ type: 'mouseDown', ...at, button: 'left', clickCount: 1 })
    wc.sendInputEvent({ type: 'mouseUp', ...at, button: 'left', clickCount: 1 })
    const t0 = Date.now()
    while (!(await js(`__jank.live(${i})`)) && Date.now() - t0 < 8000) await sleep(16)
    const ms = Date.now() - t0
    wc.sendInputEvent({ type: 'mouseMove', x: TEXT.x, y: TEXT.y })
    await sleep(600)
    const b = await capture(r)
    const d = diff(a, b)
    result.seam[theme] = { ms, live: await js(`__jank.live(${i})`), diffPct: d.diffPct, worstTile: d.worstTile, tile: d.tile }
    if (d.diffPct > 0.2 || d.worstTile > 20) {
      fs.writeFileSync(path.join(out, `seam-${theme}-still.png`), a.toPNG())
      fs.writeFileSync(path.join(out, `seam-${theme}-live.png`), b.toPNG())
      fs.writeFileSync(path.join(out, `seam-${theme}-diff.png`), d.mask.toPNG())
    }
  }
  nativeTheme.themeSource = 'light'

  result.errors = errors
  fs.writeFileSync(file, JSON.stringify(result, null, 2))
  app.exit(0)
})
