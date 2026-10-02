import { contextBridge, ipcRenderer, webUtils } from 'electron'

export interface CitecheckApi {
  getInfo(): Promise<{
    baseUrl: string
    token: string
    backendError: string | null
  }>
  /** Absolute path of a dropped File (webUtils.getPathForFile). */
  pathForFile(file: File): string
  openDocxDialog(): Promise<string | null>
  revealInFinder(path: string): void
  openExternal(url: string): void
  /** macOS open-file events; events fired before subscribe are queued. */
  onOpenFile(cb: (path: string) => void): () => void
  onMenu(cb: (cmd: 'open' | 'export' | 'new') => void): () => void
  onBackendError(cb: (msg: string) => void): () => void
  rendererReady(): void
  /** Menu enablement, e.g. 导出到 Word only on the report screen. */
  setMenuState(s: { exportEnabled: boolean }): void
  /** Debug hooks — used by shots/E2E modes only. */
  shotsMode: boolean
  e2eFile: string | null
  sampleReport(): Promise<unknown>
  onShotState(cb: (state: string) => void): () => void
  shotReady(): void
  e2eDone(info: { jobId: string | null; exportPath: string | null }): void
}

const api: CitecheckApi = {
  getInfo: () => ipcRenderer.invoke('citecheck:info'),
  pathForFile: (file) => webUtils.getPathForFile(file),
  openDocxDialog: () => ipcRenderer.invoke('citecheck:open-docx'),
  revealInFinder: (p) => ipcRenderer.invoke('citecheck:reveal', p),
  openExternal: (url) => ipcRenderer.invoke('citecheck:open-external', url),
  onOpenFile: (cb) => {
    const h = (_e: unknown, p: string) => cb(p)
    ipcRenderer.on('citecheck:open-file', h)
    return () => ipcRenderer.off('citecheck:open-file', h)
  },
  onMenu: (cb) => {
    const h = (_e: unknown, cmd: string) =>
      cb(cmd as 'open' | 'export' | 'new')
    ipcRenderer.on('citecheck:menu', h)
    return () => ipcRenderer.off('citecheck:menu', h)
  },
  onBackendError: (cb) => {
    const h = (_e: unknown, msg: string) => cb(msg)
    ipcRenderer.on('citecheck:backend-error', h)
    return () => ipcRenderer.off('citecheck:backend-error', h)
  },
  rendererReady: () => ipcRenderer.send('citecheck:renderer-ready'),
  setMenuState: (s) => ipcRenderer.send('citecheck:menu-state', s),
  shotsMode: !!process.env.CITECHECK_SHOTS,
  e2eFile: process.env.CITECHECK_E2E || null,
  sampleReport: () => ipcRenderer.invoke('citecheck:sample-report'),
  onShotState: (cb) => {
    const h = (_e: unknown, s: string) => cb(s)
    ipcRenderer.on('citecheck:shot-state', h)
    return () => ipcRenderer.off('citecheck:shot-state', h)
  },
  shotReady: () => ipcRenderer.send('citecheck:shot-ready'),
  e2eDone: (info) => ipcRenderer.send('citecheck:e2e-done', info),
}

contextBridge.exposeInMainWorld('citecheck', api)
