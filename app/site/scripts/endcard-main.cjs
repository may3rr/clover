const { app, BrowserWindow, nativeTheme } = require('electron')
const { spawn } = require('node:child_process')

const { url, out, fps } = JSON.parse(process.env.CLOVER_END)
app.dock?.hide()
app.on('window-all-closed', () => {})
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

app.whenReady().then(async () => {
  nativeTheme.themeSource = 'light'
  const win = new BrowserWindow({
    width: 3840, height: 2160, useContentSize: true, show: false,
    webPreferences: { offscreen: true, zoomFactor: 2 },
  })
  win.webContents.setFrameRate(60)
  await win.loadURL(url)
  win.webContents.setZoomFactor(2)
  const js = (s) => win.webContents.executeJavaScript(s)
  for (let i = 0; i < 300 && !(await js("!!document.querySelector('.hero-window .window.ready')")); i++) await sleep(100)
  await sleep(2400) // hero entrance settles: the first frame equals the still closing card
  const duration = await js('window.__endSetup()')
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', '3840x2160',
    '-r', String(fps), '-i', '-', '-c:v', 'h264_videotoolbox', '-b:v', '60M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out],
    { stdio: ['pipe', 'inherit', 'inherit'] })
  const n = Math.round(duration * fps)
  for (let i = 0; i < n; i++) {
    await js(`window.__render(${i / fps})`)
    const img = await win.webContents.capturePage()
    const buf = img.toBitmap()
    if (i === 0) { const s = img.getSize(); if (s.width !== 3840 || s.height !== 2160) throw new Error('capture size ' + JSON.stringify(s)) }
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r))
    if (i % 60 === 0) process.stdout.write(`\r${i}/${n}`)
  }
  ff.stdin.end()
  await new Promise((r) => ff.on('close', r))
  console.log(`\r${n} frames`)
  app.exit(0)
})
