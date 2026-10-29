// Electron side of stills.mjs: one offscreen window per shot at 1280 x 820
// CSS px, 2x, light and dark -> PNG once the app has stopped animating.
const { app, BrowserWindow, nativeTheme } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const { base, out, shots } = JSON.parse(process.env.CLOVER_STILLS)
app.dock?.hide()
app.on('window-all-closed', () => {})
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

app.whenReady().then(async () => {
  for (const theme of ['light', 'dark']) {
    nativeTheme.themeSource = theme
    for (const s of shots) {
      const win = new BrowserWindow({
        width: 2560, height: 1640, useContentSize: true, show: false,
        webPreferences: { offscreen: true, zoomFactor: 2, partition: 'stills' },
      })
      let latest = null
      win.webContents.on('paint', (_e, _d, image) => (latest = image))
      await win.loadURL(`${base}app.html?state=${encodeURIComponent(s.state)}`)
      win.webContents.setZoomFactor(2)
      const js = (code) => win.webContents.executeJavaScript(code)
      for (let i = 0; i < 300 && !(await js('!!(window.clover && window.clover.ready)')); i++) await sleep(50)
      if (s.reveal) await js(`window.clover.reveal(${JSON.stringify(s.reveal)}, 0)`)
      // settled: no running animations for a while
      for (let quiet = 0, i = 0; quiet < 10 && i < 400; i++) {
        quiet = (await js('document.getAnimations().length')) ? 0 : quiet + 1
        await sleep(50)
      }
      win.webContents.invalidate()
      await sleep(300)
      fs.writeFileSync(path.join(out, `${s.name}-${theme}.png`), latest.toPNG())
      win.destroy()
    }
  }
  app.exit(0)
})
