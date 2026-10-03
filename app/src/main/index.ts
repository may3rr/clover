import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeTheme,
  shell,
} from 'electron'
import { spawn, ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import net from 'node:net'
import path from 'node:path'
import fs from 'node:fs'

// packaged: a standalone CPython and the backend ship in Resources
// (scripts/bundle-python.sh); dev: the conda env and the repo's backend/
const PACKAGED = app.isPackaged
const PYTHON =
  process.env.CITECHECK_PYTHON ||
  (PACKAGED
    ? path.join(process.resourcesPath, 'python/bin/python3')
    : '/opt/anaconda3/envs/claude/bin/python')
/** where .env and config.toml live once packaged — never inside the bundle */
const USER_HOME = path.join(app.getPath('appData'), 'Clover')
const TOKEN = randomBytes(32).toString('hex')
const SHOTS_DIR = process.env.CITECHECK_SHOTS
const E2E_FILE = process.env.CITECHECK_E2E
const THEME = process.env.CITECHECK_THEME

// repo layout: app/out/main/index.js -> <repo>/backend
const BACKEND_DIR = PACKAGED
  ? path.join(process.resourcesPath, 'backend')
  : path.resolve(import.meta.dirname, '../../../backend')

let win: BrowserWindow | null = null
let backend: ChildProcess | null = null
let backendError: string | null = null
let port = 8765
const pendingOpenFiles: string[] = []
let rendererReady = false
let exportEnabled = false

// ---------------------------------------------------------------- backend

function portFree(p: number): Promise<boolean> {
  return new Promise((resolve) => {
    const s = net.connect({ host: '127.0.0.1', port: p })
    s.once('connect', () => {
      s.destroy()
      resolve(false)
    })
    s.once('error', () => resolve(true))
  })
}

function freePort(): Promise<number> {
  return new Promise((resolve) => {
    const srv = net.createServer()
    srv.listen(0, '127.0.0.1', () => {
      const a = srv.address()
      srv.close(() => resolve(typeof a === 'object' && a ? a.port : 8765))
    })
  })
}

async function startBackend(): Promise<void> {
  if (PACKAGED) fs.mkdirSync(USER_HOME, { recursive: true })
  if (!(await portFree(8765))) port = await freePort()
  backend = spawn(
    PYTHON,
    [
      '-m',
      'uvicorn',
      'citecheck.server:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
    ],
    {
      cwd: BACKEND_DIR,
      env: {
        ...process.env,
        CITECHECK_TOKEN: TOKEN,
        ...(PACKAGED && {
          CITECHECK_HOME: USER_HOME,
          // the bundle is read-only and must not pick up user site-packages
          PYTHONDONTWRITEBYTECODE: '1',
          PYTHONNOUSERSITE: '1',
        }),
      },
    }
  )
  backend.stdout?.on('data', (d) => process.stdout.write(`[backend] ${d}`))
  backend.stderr?.on('data', (d) => process.stderr.write(`[backend] ${d}`))
  backend.on('error', (e) => {
    backendError = `spawn: ${e.message}`
    sendBackendError()
  })
  backend.on('exit', (code) => {
    if (code && code !== 0 && !backendError) {
      backendError = `退出码 ${code}`
      sendBackendError()
    }
  })
}

function sendBackendError() {
  win?.webContents.send('citecheck:backend-error', backendError)
}

async function waitHealthy(): Promise<boolean> {
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/health`)
      if (r.ok) return true
    } catch {
      /* not up yet */
    }
    if (backendError) break
    await new Promise((r) => setTimeout(r, 400))
  }
  if (!backendError) backendError = 'health check timeout'
  return false
}

function killBackend() {
  if (backend && !backend.killed) backend.kill('SIGTERM')
  backend = null
}

// ---------------------------------------------------------------- ipc

ipcMain.handle('citecheck:info', () => ({
  baseUrl: `http://127.0.0.1:${port}`,
  token: TOKEN,
  backendError,
}))

ipcMain.handle('citecheck:open-docx', async () => {
  if (!win) return null
  const r = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    filters: [{ name: 'Word 文档', extensions: ['docx'] }],
  })
  return r.canceled || !r.filePaths.length ? null : r.filePaths[0]
})

ipcMain.handle('citecheck:pick-avatar', async () => {
  if (!win) return null
  const r = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    filters: [{ name: '图片', extensions: ['png', 'jpg', 'jpeg', 'webp'] }],
  })
  if (r.canceled || !r.filePaths.length) return null
  const p = r.filePaths[0]
  const buf = fs.readFileSync(p)
  if (buf.length > 8 * 1024 * 1024) return null
  const mime = p.endsWith('.png')
    ? 'image/png'
    : p.endsWith('.webp')
      ? 'image/webp'
      : 'image/jpeg'
  return `data:${mime};base64,${buf.toString('base64')}`
})

ipcMain.handle('citecheck:reveal', (_e, p: string) => {
  shell.showItemInFolder(p)
})

ipcMain.handle('citecheck:open-external', (_e, url: string) => {
  if (typeof url === 'string' && url.startsWith('https://')) {
    shell.openExternal(url)
  }
})

ipcMain.on('citecheck:renderer-ready', () => {
  rendererReady = true
  flushOpenFiles()
})

ipcMain.on('citecheck:menu-state', (_e, s: { exportEnabled: boolean }) => {
  if (s.exportEnabled !== exportEnabled) {
    exportEnabled = s.exportEnabled
    buildMenu()
  }
})

// sample report + shot capture (only used under CITECHECK_SHOTS)
ipcMain.handle('citecheck:sample-report', () => {
  const p = path.resolve(app.getAppPath(), 'fixtures/report.sample.json')
  return JSON.parse(fs.readFileSync(p, 'utf-8'))
})
ipcMain.on('citecheck:e2e-done', (_e, info: unknown) => {
  console.log(`E2E_RESULT ${JSON.stringify(info)}`)
  app.quit()
})

const SHOT_STATES = [
  'onboarding-intro',
  'onboarding-model',
  'onboarding-profile',
  'onboarding-privacy',
  'credits',
  'empty',
  'empty-dragover',
  'running-shimmer',
  'running-mid',
  'running-done',
  'report',
  'report-selected',
  'report-filter-support',
  'detail-support',
  'detail-authenticity',
  'detail-distribution',
  'detail-norms',
  'detail-revision',
  'settings-account',
  'settings-comments',
  'settings-model',
  'settings-usage',
  'settings-about',
]

function shotReady(): Promise<void> {
  return new Promise((resolve) => {
    ipcMain.once('citecheck:shot-ready', () => resolve())
    setTimeout(resolve, 8000) // never hang the run
  })
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

// Prefer the real window (vibrancy + traffic lights) via screencapture;
// fall back to capturePage if Screen Recording permission is missing.
// screencapture occasionally reads the previous frame — capture twice and
// keep the second when it differs (a one-frame lag then heals itself).
async function captureOnce(file: string): Promise<boolean> {
  return new Promise(async (resolve) => {
    try {
      const src = win!.getMediaSourceId() // "window:<CGWindowID>:0"
      const wid = src.split(':')[1]
      const { execFile } = await import('node:child_process')
      execFile(
        '/usr/sbin/screencapture',
        ['-x', '-o', `-l${wid}`, file],
        (err) => {
          resolve(
            !err && fs.existsSync(file) && fs.statSync(file).size > 10000
          )
        }
      )
    } catch {
      resolve(false)
    }
  })
}

async function captureWindow(file: string): Promise<'window' | 'page'> {
  const tmp = `${file}.tmp.png`
  const ok1 = await captureOnce(tmp)
  if (!ok1) {
    const img = await win!.webContents.capturePage()
    fs.writeFileSync(file, img.toPNG())
    return 'page'
  }
  await sleep(350)
  const ok2 = await captureOnce(file)
  // second pass may differ if the first was a stale frame — keep it
  if (!ok2) fs.copyFileSync(tmp, file)
  fs.rmSync(tmp, { force: true })
  return 'window'
}

async function runShots() {
  if (!SHOTS_DIR || !win) return
  await sleep(600) // renderer mounts, subscribes, sends renderer-ready
  fs.mkdirSync(SHOTS_DIR, { recursive: true })
  let method: 'window' | 'page' | null = null
  for (const theme of ['light', 'dark'] as const) {
    nativeTheme.themeSource = theme
    await sleep(400)
    for (const state of SHOT_STATES) {
      const ready = shotReady()
      win.webContents.send('citecheck:shot-state', state)
      await ready
      await sleep(300) // let the 200ms detail/list transitions finish
      const p = path.join(SHOTS_DIR, `${theme}-${state}.png`)
      method = await captureWindow(p)
      console.log(`shot saved (${method}): ${p}`)
    }
  }
  console.log(`SHOTS_METHOD ${method}`)
  app.quit()
}

// macOS "open-file" — Dock drops / Finder Open With
app.on('open-file', (e, p) => {
  e.preventDefault()
  pendingOpenFiles.push(p)
  flushOpenFiles()
})

function flushOpenFiles() {
  if (!rendererReady || !win) return
  while (pendingOpenFiles.length) {
    win.webContents.send('citecheck:open-file', pendingOpenFiles.shift())
  }
}

// ---------------------------------------------------------------- menu

function menuClick(cmd: string) {
  return () => win?.webContents.send('citecheck:menu', cmd)
}

function buildMenu() {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: app.name,
      submenu: [
        { role: 'about', label: `关于${app.name}` },
        { type: 'separator' },
        { role: 'services', label: '服务' },
        { type: 'separator' },
        { role: 'hide', label: `隐藏${app.name}` },
        { role: 'hideOthers', label: '隐藏其他' },
        { role: 'unhide', label: '全部显示' },
        { type: 'separator' },
        { role: 'quit', label: `退出${app.name}` },
      ],
    },
    {
      label: '文件',
      submenu: [
        {
          label: '打开论文…',
          accelerator: 'CmdOrCtrl+O',
          click: menuClick('open'),
        },
        {
          label: '导出到 Word',
          accelerator: 'CmdOrCtrl+E',
          enabled: exportEnabled,
          click: menuClick('export'),
        },
        { type: 'separator' },
        {
          label: '检查另一篇',
          accelerator: 'CmdOrCtrl+N',
          click: menuClick('new'),
        },
      ],
    },
    { label: '编辑', role: 'editMenu' },
    { label: '显示', role: 'viewMenu' },
    { label: '窗口', role: 'windowMenu' },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

// ---------------------------------------------------------------- window

async function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1100,
    minHeight: 720,
    show: false,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 20, y: 20 },
    vibrancy: 'sidebar',
    visualEffectState: 'followWindow',
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(import.meta.dirname, '../preload/index.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      // keep compositing while occluded — otherwise screencapture reads a
      // stale window surface in shot mode (DOM updated, pixels not)
      backgroundThrottling: false,
    },
  })

  if (THEME === 'light' || THEME === 'dark') {
    nativeTheme.themeSource = THEME
  }

  // surface renderer console in shot/e2e runs
  if (SHOTS_DIR || E2E_FILE) {
    win.webContents.on('console-message', (_e, _l, msg) =>
      console.log(`[renderer] ${msg}`)
    )
  }

  const devUrl = process.env.ELECTRON_RENDERER_URL
  if (devUrl) {
    await win.loadURL(devUrl)
  } else {
    await win.loadFile(
      path.join(import.meta.dirname, '../renderer/index.html')
    )
  }

  // shot mode: real onscreen window so capturePage gets painted pixels;
  // driven by the state loop
  if (SHOTS_DIR) {
    win.show()
    runShots()
  }
}

// ---------------------------------------------------------------- boot

app.whenReady().then(async () => {
  buildMenu()
  if (SHOTS_DIR) {
    // shots run offline from the bundled sample report — no backend
    await createWindow()
    return
  }
  await startBackend()
  const healthy = await waitHealthy()
  await createWindow()
  win!.show()
  if (!healthy) sendBackendError()
})

app.on('before-quit', killBackend)
app.on('will-quit', killBackend)
process.on('exit', killBackend)

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0 && backend && !backendError) {
    createWindow()
  }
})


