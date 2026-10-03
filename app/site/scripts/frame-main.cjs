// Electron side of frame.mjs: render frame.html at 1920 x 1080 CSS px,
// 2x, light and dark -> PNG + the slot rectangle in output pixels.
const { app, BrowserWindow, nativeTheme } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const { base, out } = JSON.parse(process.env.CLOVER_FRAME)
app.dock?.hide()
app.on('window-all-closed', () => {})
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

app.whenReady().then(async () => {
  let slot = null
  for (const theme of ['light', 'dark']) {
    nativeTheme.themeSource = theme
    const win = new BrowserWindow({
      width: 3840, height: 2160, useContentSize: true, show: false,
      webPreferences: { offscreen: true, zoomFactor: 2 },
    })
    let latest = null
    win.webContents.on('paint', (_e, _d, image) => (latest = image))
    await win.loadURL(base + 'frame.html')
    win.webContents.setZoomFactor(2)
    await sleep(1500)
    slot = await win.webContents.executeJavaScript('window.__slot')
    fs.writeFileSync(path.join(out, `frame-${theme}.png`), latest.toPNG())
    win.destroy()
  }
  const s = Object.fromEntries(Object.entries(slot).map(([k, v]) => [k, Math.round(v * 2)]))
  fs.writeFileSync(path.join(out, 'slot.json'), JSON.stringify(s, null, 2))
  console.log('slot (4K px)', s)
  app.exit(0)
})
