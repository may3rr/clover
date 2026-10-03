/** In-browser stand-in for the local backend and the Electron preload, so
 *  the real renderer (App.tsx and every screen) runs unchanged on a static
 *  page. Reports come from real pipeline runs (demo/curate_showcase.py);
 *  a "check" replays the showcase run's event stream on a fixed timeline. */
import type { CitecheckApi } from '../../../src/preload/index'
import type { Report } from '../../../src/renderer/src/types/report'
import { anchorsFromReport } from '../../../src/renderer/src/lib/outline'

const BASE = 'https://clover.local'
const HOME = '/Users/liming/Documents'
const SHOWCASE_FILE = 'vericite_emnlp.docx'
const GROUNDED_FILE = 'grounded_but_wrong.docx'
const SAMPLE_DOCX = './samples/clover-sample.docx'

export const PREFS = {
  name: '李明',
  avatar: { kind: 'color', color: 'teal', image: null },
  comment_author: '',
  comment_initials: '',
  onboarded: true,
}

interface Data {
  showcase: Report
  grounded: Report
  outline: unknown
}
// one shared request: the state driver and App both wait on it, and the
// driver must not run ahead of App's own sampleReport() handler
let data: Promise<Data> | null = null
export function loadData(): Promise<Data> {
  if (data) return data
  const get = (p: string) => fetch(p).then((r) => r.json())
  data = Promise.all([
    get('./data/showcase.json'),
    get('./data/grounded.json'),
    get('./data/showcase_outline.json'),
  ]).then(([showcase, grounded, outline]) => ({ showcase, grounded, outline }))
  return data
}

// ----------------------------------------------------------------- routes
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

function meta(id: string, file: string, r: Report, hoursAgo: number) {
  const n = (s: string) => (r.findings ?? []).filter((f) => f.severity === s).length
  return {
    id,
    filename: file,
    title: r.document?.title ?? file,
    created_at: new Date(Date.now() - hoursAgo * 3600e3).toISOString(),
    n_high: n('high'),
    n_medium: n('medium'),
    n_low: n('low'),
  }
}

let prefs = { ...PREFS }
/** set by the tour runner: exports don't trigger a browser download */
export const flags = { quietExport: false }

async function route(method: string, path: string, body: unknown): Promise<Response> {
  const d = await loadData()
  const m = (re: RegExp) => path.match(re)
  if (path === '/prefs') {
    if (method === 'PUT') prefs = { ...prefs, ...(body as object) }
    return json(prefs)
  }
  if (path === '/benchmarks')
    return json([{ id: 'arxiv_cs_cl', name: 'arXiv 计算语言学', n_papers: 150 }])
  if (path === '/reports')
    return json([
      // id 'shot' = the job id App's state driver uses, so the open report
      // and its history row are the same entry
      meta('shot', SHOWCASE_FILE, d.showcase, 2),
      meta('grounded', GROUNDED_FILE, d.grounded, 26),
    ])
  if (m(/^\/reports\/[^/]+$/)) {
    if (method === 'DELETE') return json({ ok: true })
    return json(path.endsWith('grounded') ? d.grounded : d.showcase)
  }
  if (m(/\/export$/)) {
    const stem = path.includes('grounded') ? GROUNDED_FILE : SHOWCASE_FILE
    return json({ path: `${HOME}/${stem.replace(/\.docx$/, '')}（Clover）.docx` })
  }
  if (path === '/analyze') return json({ job_id: 'shot' })
  if (m(/^\/jobs\/[^/]+\/report$/)) return json(d.showcase)
  if (path === '/models')
    return json({
      models: [
        'qwen3.7-flash',
        'qwen3.7-max',
        'qwen3.8-flash',
        'qwen3.8-max',
        'qwen3.8-plus',
      ],
    })
  if (path === '/config') return json({ ok: true })
  return json({ detail: 'not found' }, 404)
}

const nativeFetch = window.fetch.bind(window)
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  if (!url.startsWith(BASE)) return nativeFetch(input, init)
  const path = new URL(url).pathname
  let body: unknown = null
  if (typeof init?.body === 'string') {
    try {
      body = JSON.parse(init.body)
    } catch {
      /* form data etc. */
    }
  }
  // a beat of latency so loading states look like the app's
  await new Promise((r) => setTimeout(r, 60))
  return route((init?.method ?? 'GET').toUpperCase(), path, body)
}

// ------------------------------------------------------------ SSE replay
/** Seconds into the replay. The real run (cached sources) took 7.7 s with
 *  the same order: parse, the two local layers, then authenticity and
 *  support, then the venue overview. */
const TIMELINE = {
  parsed: 0.5,
  running: 0.9,
  distribution: 2.2,
  norms: 2.8,
  authenticity: 5.2,
  support: 6.6,
  overviewRun: 6.8,
  overviewOk: 8.4,
  done: 9.0,
}

class ReplayEventSource extends EventTarget {
  onerror: ((e: Event) => void) | null = null
  readyState = 1
  private timers: number[] = []
  constructor(public url: string) {
    super()
    loadData().then((d) => this.play(d))
  }
  private at(sec: number, type: string, payload: object) {
    this.timers.push(
      window.setTimeout(() => {
        if (this.readyState === 2) return
        this.dispatchEvent(
          new MessageEvent(type, { data: JSON.stringify({ type, ...payload }) })
        )
      }, sec * 1000)
    )
  }
  private play(d: Data) {
    const anchors = anchorsFromReport(d.showcase)
    const counts: Record<string, number> = {}
    for (const f of d.showcase.findings ?? [])
      counts[f.layer ?? ''] = (counts[f.layer ?? ''] ?? 0) + 1
    const T = TIMELINE
    this.at(T.parsed, 'parsed', { outline: d.outline })
    for (const l of ['support', 'authenticity', 'distribution', 'norms'])
      this.at(T.running, 'layer', { layer: l, status: 'running' })
    for (const l of ['distribution', 'norms', 'authenticity', 'support'] as const)
      this.at(T[l], 'layer', {
        layer: l,
        status: 'done',
        findings: counts[l] ?? 0,
        anchors: anchors[l] ?? [],
      })
    this.at(T.overviewRun, 'overview', { status: 'running' })
    this.at(T.overviewOk, 'overview', { status: 'ok' })
    this.at(T.done, 'done', {})
  }
  close() {
    this.readyState = 2
    this.timers.forEach(clearTimeout)
  }
}
const NativeES = window.EventSource
window.EventSource = function (url: string | URL, init?: EventSourceInit) {
  const u = String(url)
  if (u.startsWith(BASE)) return new ReplayEventSource(u)
  return new NativeES(u, init)
} as unknown as typeof EventSource

// --------------------------------------------------------------- preload
type ShotCb = (state: string) => void
let shotCb: ShotCb | null = null
let shotDone: (() => void) | null = null
const noop = () => () => {}

function download(href: string, name: string) {
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
}

const api: CitecheckApi = {
  getInfo: async () => ({ baseUrl: BASE, token: '', backendError: null }),
  pathForFile: () => `${HOME}/${SHOWCASE_FILE}`,
  openDocxDialog: async () => `${HOME}/${SHOWCASE_FILE}`,
  pickAvatar: async () => null,
  revealInFinder: (p) => {
    if (!flags.quietExport) download(SAMPLE_DOCX, p.split('/').pop() ?? 'clover.docx')
  },
  openExternal: (url) => window.open(url, '_blank', 'noopener'),
  onOpenFile: noop,
  onMenu: noop,
  onBackendError: noop,
  rendererReady: () => {},
  setMenuState: () => {},
  shotsMode: false,
  sampleData: true,
  e2eFile: null,
  sampleReport: () => loadData().then((d) => d.showcase),
  onShotState: (cb) => {
    shotCb = cb
    return () => {
      if (shotCb === cb) shotCb = null
    }
  },
  shotReady: () => {
    shotDone?.()
    shotDone = null
  },
  e2eDone: () => {},
}
window.citecheck = api

/** Drive the app into a named state (lib/shots.ts) once it is listening. */
export async function go(state: string): Promise<void> {
  await loadData()
  for (let i = 0; i < 200 && !shotCb; i++) await new Promise((r) => setTimeout(r, 16))
  // App wires its refs in the sampleReport().then — give it one more tick
  await new Promise((r) => setTimeout(r, 0))
  await new Promise<void>((resolve) => {
    shotDone = resolve
    shotCb?.(state)
  })
}
