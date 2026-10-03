// Electron side of record.mjs: offscreen window -> fixed-rate frames ->
// ffmpeg. One window per job so every scene starts from a clean boot.
const { app, BrowserWindow, nativeTheme } = require('electron')
const { spawn, spawnSync } = require('node:child_process')
const path = require('node:path')

const cfg = JSON.parse(process.env.CLOVER_RECORD)
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required')
app.dock?.hide()
// one window per job: closing the last one must not quit between jobs
app.on('window-all-closed', () => {})

const W = cfg.frame || cfg.jobs[0].url.startsWith('index') ? 1600 : 1280
const H = cfg.frame || cfg.jobs[0].url.startsWith('index') ? 1000 : 820
const hasVT = /h264_videotoolbox/.test(
  spawnSync('ffmpeg', ['-hide_banner', '-encoders'], { encoding: 'utf8' }).stdout || ''
)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function record(job) {
  // offscreen ignores the device scale factor: render a scale-times larger
  // window zoomed by the same factor, so layout still sees W x H CSS px
  const win = new BrowserWindow({
    width: W * cfg.scale,
    height: H * cfg.scale,
    useContentSize: true,
    show: false,
    webPreferences: { offscreen: true, backgroundThrottling: false, zoomFactor: cfg.scale },
  })
  win.webContents.setFrameRate(cfg.fps)
  const errors = []
  win.webContents.on('console-message', (e) => {
    const { level, message } = e
    if (level === 'error' || level === 3) errors.push(message)
  })
  let latest = null
  let size = null
  win.webContents.on('paint', (_e, _dirty, image) => {
    latest = image.toBitmap()
    size = image.getSize()
  })
  await win.loadURL(cfg.base + job.url)
  win.webContents.setZoomFactor(cfg.scale)

  let ff = null
  let timer = null
  let frames = 0
  const file = path.join(cfg.out, `${job.name}${cfg.dark ? '-dark' : ''}.mp4`)
  const startEncoder = () => {
    const { width, height } = size
    const enc = hasVT
      ? ['-c:v', 'h264_videotoolbox', '-b:v', `${Math.round((width * height) / 1e5)}M`, '-allow_sw', '1']
      : ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16']
    ff = spawn('ffmpeg', [
      '-y', '-loglevel', 'error',
      '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', `${width}x${height}`, '-r', String(cfg.fps),
      '-i', '-',
      ...enc, '-pix_fmt', 'yuv420p', '-movflags', '+faststart', file,
    ], { stdio: ['pipe', 'inherit', 'inherit'] })
    // constant-rate writer on the wall clock: paint only fires on change,
    // and timers drift, so top up to the frame count the elapsed time needs
    const start = Date.now()
    timer = setInterval(() => {
      const due = Math.floor(((Date.now() - start) / 1000) * cfg.fps)
      while (frames < due && latest && latest.length === width * height * 4) {
        ff.stdin.write(latest)
        frames++
      }
    }, 1000 / cfg.fps / 2)
  }

  const isDone = () => win.webContents.executeJavaScript('!!(window.clover && window.clover.tourDone)')
  // wait for the first painted frame
  for (let i = 0; i < 200 && !size; i++) await sleep(25)
  if (!cfg.check) startEncoder()
  const t0 = Date.now()
  if (job.seconds) await sleep(job.seconds * 1000)
  else {
    while (!(await isDone())) {
      if (Date.now() - t0 > 180000) throw new Error(`${job.name}: tour did not finish`)
      await sleep(100)
    }
    await sleep(800) // let the last transition settle
  }
  if (ff) {
    clearInterval(timer)
    ff.stdin.end()
    await new Promise((r) => ff.on('close', r))
  }
  win.destroy()
  const secs = ((Date.now() - t0) / 1000).toFixed(1)
  console.log(
    cfg.check
      ? `${job.name}: ok in ${secs}s${errors.length ? `, console errors:\n  ${errors.join('\n  ')}` : ''}`
      : `${path.relative(process.cwd(), file)}  ${frames} frames, ${secs}s${errors.length ? `  (console errors: ${errors.length})` : ''}`
  )
  return errors.length
}

app.whenReady().then(async () => {
  nativeTheme.themeSource = cfg.dark ? 'dark' : 'light'
  let failed = 0
  for (const job of cfg.jobs) {
    try {
      failed += (await record(job)) ? 1 : 0
    } catch (e) {
      console.error(String(e))
      failed++
    }
  }
  app.exit(failed ? 1 : 0)
})
