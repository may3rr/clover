// Electron side of frame.mjs: render a page at `size` CSS px (1920 x 1080 by default), 2x,
// light and dark -> PNG (+ the window slot in output pixels, if the page
// exposes window.__slot). `ready` is a selector to wait for, if any.
const { app, BrowserWindow, nativeTheme } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const { base, out, page, name, ready, themes, size = [1920, 1080] } = JSON.parse(process.env.CLOVER_FRAME)
app.dock?.hide()
app.on('window-all-closed', () => {})
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

app.whenReady().then(async () => {
  let slot = null
  for (const theme of themes) {
    nativeTheme.themeSource = theme
    const win = new BrowserWindow({
      width: size[0] * 2, height: size[1] * 2, useContentSize: true, show: false,
      webPreferences: { offscreen: true, zoomFactor: 2 },
    })
    let latest = null
    win.webContents.on('paint', (_e, _d, image) => (latest = image))
    await win.loadURL(base + page)
    win.webContents.setZoomFactor(2)
    if (ready)
      for (let i = 0; i < 300; i++) {
        if (await win.webContents.executeJavaScript(`!!document.querySelector(${JSON.stringify(ready)})`)) break
        await sleep(100)
      }
    await sleep(2200) // entrance animations settle
    slot = await win.webContents.executeJavaScript('window.__slot || null')
    fs.writeFileSync(path.join(out, `${name}-${theme}.png`), latest.toPNG())
    win.destroy()
  }
  if (slot) {
    const s = Object.fromEntries(Object.entries(slot).map(([k, v]) => [k, Math.round(v * 2)]))
    fs.writeFileSync(path.join(out, `${name}.slot.json`), JSON.stringify(s, null, 2))
  }
  app.exit(0)
})
