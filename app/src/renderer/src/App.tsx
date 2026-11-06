import { useCallback, useEffect, useRef, useState } from 'react'
import { getInfo, apiFetch, eventsUrl } from './lib/api'
import type { Report } from './types/report'
import Empty from './screens/Empty'
import Running, { type LayerUI } from './screens/Running'
import ReportScreen from './screens/ReportScreen'
import LibraryConfirm from './screens/LibraryConfirm'
import Scanning from './screens/Scanning'
import { baseName, type LibraryScan } from './lib/library'
import ErrorScreen from './screens/Error'
import Settings from './screens/Settings'
import Onboarding, { type OnboardStep } from './screens/Onboarding'
import Credits from './components/Credits'
import { applyShotState, type ShotCtx, type VenueSample } from './lib/shots'
import { morph } from './lib/vt'
import type { Outline, SkAnchor } from './lib/outline'
import { getPrefs, DEFAULT_PREFS, type Prefs } from './lib/prefs'
import { ACCEPT_ERROR, isPaperPath, looksLikeFolder } from './lib/accept'
import { readVenue, saveVenue } from './lib/targetVenue'
import type { RebenchState } from './screens/ReportScreen'


type Screen =
  | 'empty'
  | 'library'
  | 'scanning'
  | 'running'
  | 'report'
  | 'error'
  | 'settings'
  | 'onboarding'

export default function App() {
  const [screen, setScreen] = useState<Screen>('empty')
  const [scanId, setScanId] = useState('')
  const scanToken = useRef('')
  const [info, setInfo] = useState<Awaited<
    ReturnType<typeof getInfo>
  > | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  // 期刊对标后到：报告先开，对标算完再补；undefined = 沿用 report.overview
  const [lateOverview, setLateOverview] = useState<Report['overview']>(undefined)
  // a venue typed on a finished report: the run behind it, while it lasts
  const [rebench, setRebench] = useState<RebenchState | null>(null)
  const rebenchToken = useRef<string | null>(null)
  // the report view's identity: a report swapped in after benchmarking is
  // the same view (selection, scroll, panes stay), a new check is not
  const [viewKey, setViewKey] = useState<string | null>(null)
  const [benchmark, setBenchmark] = useState('arxiv_cs_cl')
  const [venue, setVenueState] = useState(readVenue)
  // the target venue: typed on the home screen, edited on the
  // confirmation page, sent with the scan and the run
  const setVenue = useCallback((v: string) => {
    setVenueState(v)
    saveVenue(v)
  }, [])
  // venue the running job was started with ('' = overview off)
  const [runVenue, setRunVenue] = useState('')
  const [jobError, setJobError] = useState<string | null>(null)
  // 文献文件夹 picked on the home screen, and the pending link table
  const [libraryDir, setLibraryDir] = useState<string | null>(null)
  const [scan, setScan] = useState<LibraryScan | null>(null)
  const [fileName, setFileName] = useState('paper.docx')
  const exportRef = useRef<(() => void) | null>(null)
  const shotState = useRef<ShotCtx>({})
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS)
  const settingsFrom = useRef<Screen>('empty')
  const [onboardStep, setOnboardStep] = useState<OnboardStep>(0)
  const [credits, setCredits] = useState<false | 'live' | 'shot'>(false)
  const [settingsSection, setSettingsSection] = useState<
    'account' | 'comments' | 'model' | 'usage' | 'about'
  >('account')

  // ---------------------------------------------------------------- boot
  // macOS dims selection and tiles while the window is in the background
  useEffect(() => {
    const set = () =>
      (document.documentElement.dataset.windowFocus = String(
        // shot runs capture an often-unfocused window; show the active look
        window.citecheck.shotsMode || document.hasFocus()
      ))
    set()
    window.addEventListener('focus', set)
    window.addEventListener('blur', set)
    return () => {
      window.removeEventListener('focus', set)
      window.removeEventListener('blur', set)
    }
  }, [])

  useEffect(() => {
    getPrefs().then((p) => {
      setPrefs(p)
      // first run: guide + privacy consent before anything else
      if (!p.onboarded && !window.citecheck.shotsMode && !window.citecheck.e2eFile)
        setScreen((s) => (s === 'error' ? s : 'onboarding'))
    })
    getInfo().then((i) => {
      setInfo(i)
      if (i.backendError) setScreen('error')
    })
    const offErr = window.citecheck.onBackendError(() => {
      setScreen('error')
      setInfo((i) => (i ? { ...i, backendError: 'backend died' } : i))
    })
    window.citecheck.rendererReady()
    return offErr
  }, [])

  // ------------------------------------------------------------ analyze
  const startJob = useCallback(
    async (path: string, extra: Record<string, string> = {}) => {
      setJobError(null)
      setFileName(baseName(path))
      try {
        const fd = new FormData()
        fd.append('path', path)
        fd.append('benchmark', benchmark)
        const target = (extra.venue ?? venue).trim()
        fd.append('venue', target)
        for (const [k, v] of Object.entries(extra)) if (k !== 'venue') fd.append(k, v)
        const r = await apiFetch('/analyze', { method: 'POST', body: fd })
        if (!r.ok) {
          // the backend says why (no API key, unreadable archive); only an
          // unexplained refusal is blamed on the file format
          const { detail } = (await r.json().catch(() => ({}))) as {
            detail?: unknown
          }
          setJobError(typeof detail === 'string' ? detail : ACCEPT_ERROR)
          return
        }
        const { job_id } = (await r.json()) as { job_id: string }
        // the front sheet flies into the first skeleton page
        morph(() => {
          setJobId(job_id)
          setViewKey(null)
          setRunVenue(target)
          setScreen('running')
        })
      } catch {
        setJobError('无法连接本地服务。请重新打开应用。')
      }
    },
    [benchmark, venue]
  )

  // a paper folder (docx + ref/), or a docx with a chosen reference
  // folder, goes through the link confirmation step first; a folder the
  // scan can't use (LaTeX without ref/, …) runs as before
  const analyze = useCallback(
    async (path: string) => {
      setJobError(null)
      const folderLike = !isPaperPath(path)
      if (!folderLike && !libraryDir) return startJob(path)
      // 扫描可能要几十秒：立刻切到扫描页，显示后端上报的真实阶段
      const id = Math.random().toString(36).slice(2, 10)
      scanToken.current = id
      setScanId(id)
      setFileName(baseName(path))
      setScreen('scanning')
      const stale = () => scanToken.current !== id
      try {
        const fd = new FormData()
        fd.append('path', path)
        fd.append('scan_id', id)
        fd.append('venue', venue.trim())
        if (libraryDir) fd.append('library', libraryDir)
        const r = await apiFetch('/library/scan', { method: 'POST', body: fd })
        if (stale()) return // 用户已取消
        if (r.ok) {
          const sc = (await r.json()) as LibraryScan
          if (stale()) return
          setFileName(baseName(sc.paper))
          morph(() => {
            setScan(sc)
            setScreen('library')
          })
          return
        }
        if (libraryDir) {
          const { detail } = (await r.json().catch(() => ({}))) as { detail?: string }
          setJobError(detail ?? ACCEPT_ERROR)
          setScreen('empty')
          return
        }
      } catch {
        if (stale()) return
        setJobError('无法连接本地服务。请重新打开应用。')
        setScreen('empty')
        return
      }
      // 没有可用的文献文件夹（如没有 ref/ 的 LaTeX 项目）：按单文件体检
      await startJob(path)
      if (!stale()) setScreen((s) => (s === 'scanning' ? 'empty' : s))
    },
    [libraryDir, startJob, venue]
  )

  const pickLibrary = useCallback(async () => {
    const p = await window.citecheck.openFolderDialog()
    if (p) setLibraryDir(p)
  }, [])

  const openDialog = useCallback(async () => {
    const p = await window.citecheck.openDocxDialog()
    if (p) analyze(p)
  }, [analyze])

  const reset = useCallback(() => {
    rebenchToken.current = null
    setRebench(null)
    setScan(null)
    setScreen('empty')
    setJobId(null)
    setViewKey(null)
    setReport(null)
    setLateOverview(undefined)
    setJobError(null)
  }, [])

  // open a past report from the home history — no re-run, no re-upload
  const openReport = useCallback(async (id: string) => {
    rebenchToken.current = null
    setRebench(null)
    setJobError(null)
    try {
      const r = await apiFetch(`/reports/${id}`)
      if (!r.ok) {
        setJobError('读取报告失败。这条记录可能已被删除。')
        return
      }
      const rep = (await r.json()) as Report
      morph(() => {
        setJobId(id)
        setViewKey(null)
        setLateOverview(undefined)
        setReport(rep)
        setScreen('report')
      })
    } catch {
      setJobError('无法连接本地服务。请重新打开应用。')
    }
  }, [])

  // a target venue typed after the check: the manuscript runs again with it
  // while this report stays on screen (cached, so the four layers replay);
  // the new report swaps in when its layers are done and the venue overview
  // then arrives the usual deferred way
  const benchmarkReport = useCallback(
    async (name: string) => {
      if (!jobId) return
      const token = Math.random().toString(36).slice(2, 10)
      rebenchToken.current = token
      const live = () => rebenchToken.current === token
      const fail = (error: string) => {
        if (live()) setRebench({ venue: name, error })
      }
      setRebench({ venue: name })
      // the home field is the one source of the target venue: keep it in step
      setVenue(name)
      try {
        const fd = new FormData()
        fd.append('venue', name)
        const r = await apiFetch(`/reports/${jobId}/venue`, {
          method: 'POST',
          body: fd,
        })
        const d = (await r.json().catch(() => ({}))) as {
          job_id?: string
          detail?: unknown
          edited?: boolean
        }
        if (!r.ok || !d.job_id) {
          fail(
            typeof d.detail === 'string'
              ? d.detail
              : '无法开始对标。请退出 Clover 后重新打开，再试一次。'
          )
          return
        }
        const next = d.job_id
        const edited = !!d.edited
        if (live()) setRebench({ venue: name, edited })
        const es = new EventSource(await eventsUrl(next))
        es.addEventListener('progress', (ev) => {
          const label = JSON.parse((ev as MessageEvent).data).label
          if (live() && typeof label === 'string')
            setRebench({ venue: name, step: label, edited })
        })
        es.addEventListener('done', async () => {
          es.close()
          if (!live()) return
          const rr = await apiFetch(`/jobs/${next}/report`)
          if (!rr.ok) {
            fail('无法读取对标后的报告。请从最近检查里重新打开这篇论文。')
            return
          }
          const rep = (await rr.json()) as Report
          if (!live()) return
          rebenchToken.current = null
          // swapped in place, no view transition: the page stays where the
          // reader is and only the changed parts update
          setViewKey((k) => k ?? jobId)
          setRebench(null)
          setLateOverview(undefined)
          setJobId(next)
          setReport(rep)
        })
        es.addEventListener('failed', (ev) => {
          es.close()
          fail(
            JSON.parse((ev as MessageEvent).data).error ??
              '对标没有完成。请稍后再试。'
          )
        })
        es.onerror = () => {
          es.close()
          fail('连接中断，对标没有完成。请再试一次。')
        }
      } catch {
        fail('无法连接本地服务。请退出 Clover 后重新打开。')
      }
    },
    [jobId, setVenue]
  )

  // ------------------------------------------------------- job lifecycle
  const onJobDone = useCallback(async () => {
    if (!jobId) return
    const r = await apiFetch(`/jobs/${jobId}/report`)
    if (!r.ok) {
      setJobError('读取报告失败。请重新体检。')
      return
    }
    const rep = (await r.json()) as Report
    // skeleton page 1 morphs into the reading page, panel into inspector
    morph(() => {
      setLateOverview(undefined)
      setReport(rep)
      setScreen('report')
    })
  }, [jobId])

  // 报告打开时对标还没好：继续订阅这个任务的事件，等 overview_done 后只取回对标
  useEffect(() => {
    if (screen !== 'report' || !jobId || report?.overview?.status !== 'pending')
      return
    let es: EventSource | null = null
    let cancelled = false
    const settle = async (path: string) => {
      es?.close()
      try {
        const r = await apiFetch(path)
        if (cancelled) return
        if (r.ok) setLateOverview(((await r.json()) as Report).overview ?? null)
        else setLateOverview(null)
      } catch {
        if (!cancelled) setLateOverview(null)
      }
    }
    eventsUrl(jobId).then((url) => {
      if (cancelled) return
      es = new EventSource(url)
      es.addEventListener('overview_done', () => settle(`/jobs/${jobId}/report`))
      // 任务已不在（服务重启）：读落库的报告，后端会把 pending 改成 unavailable
      es.onerror = () => settle(`/reports/${jobId}`)
    })
    return () => {
      cancelled = true
      es?.close()
    }
  }, [screen, jobId, report])

  const onJobFailed = useCallback((error: string) => {
    setJobError(error)
  }, [])

  // -------------------------------------------------------------- menu
  useEffect(() => {
    const offFile = window.citecheck.onOpenFile((p) => {
      if (isPaperPath(p) || looksLikeFolder(p)) analyze(p)
      else setJobError(ACCEPT_ERROR)
    })
    const offMenu = window.citecheck.onMenu((cmd) => {
      if (cmd === 'open') openDialog()
      else if (cmd === 'new') reset()
      else if (cmd === 'export') exportRef.current?.()
    })
    return () => {
      offFile()
      offMenu()
    }
  }, [analyze, openDialog, reset])

  // export is only enabled on the report screen; LaTeX exports sources
  useEffect(() => {
    window.citecheck.setMenuState({
      exportEnabled: screen === 'report',
      exportLabel:
        report?.document.source_format === 'tex'
          ? '导出批注版源码'
          : '导出到 Word',
    })
  }, [screen, report])

  // --------------------------------------------------------- shots hook
  useEffect(() => {
    if (!window.citecheck.sampleData) return
    window.citecheck.sampleReport().then((r) => {
      setJobId('shot') // report/running branches require a truthy jobId
      shotState.current.report = r as Report
      shotState.current.setScreen = setScreen
      shotState.current.setReport = setReport
      shotState.current.setLayers = (l) => setShotLayers(l)
      shotState.current.setOutline = (o) => setShotOutline(o)
      shotState.current.setAnchors = (a) => setShotAnchors(a)
      shotState.current.selectItem = (id, open) =>
        setExtSel({ id, open: open !== false })
      shotState.current.setFilter = (l) => setExtFilter({ layer: l })
      shotState.current.setDrag = (v) => setDragHint(v)
      shotState.current.setPrefs = (p) => setPrefs(p)
      shotState.current.setShotPanes = (p) => setShotPanes(p)
      shotState.current.setSettingsSection = (s) => setSettingsSection(s)
      shotState.current.setOnboardStep = (n) => setOnboardStep(n)
      shotState.current.setCredits = (v) => setCredits(v ? 'shot' : false)
      shotState.current.setScan = (sc, f) => {
        setScan(sc)
        setShotLibFilter(f ?? null)
      }
    })
    window.citecheck.sampleVenue?.().then((v) => {
      shotState.current.venue = v as VenueSample
    })
  }, [])
  const [shotLibFilter, setShotLibFilter] = useState<'links' | 'exemplars' | null>(null)
  const [shotLayers, setShotLayers] = useState<LayerUI | null>(null)
  const [shotOutline, setShotOutline] = useState<Outline | null>(null)
  const [shotAnchors, setShotAnchors] = useState<
    Record<string, SkAnchor[]> | null
  >(null)
  const [dragHint, setDragHint] = useState(false)
  const [extSel, setExtSel] = useState<{ id: string | null; open: boolean } | null>(
    null
  )
  const [extFilter, setExtFilter] = useState<{ layer: string | null } | null>(
    null
  )
  const [shotPanes, setShotPanes] = useState<{
    left: boolean
    right: boolean
  } | null>(null)

  useEffect(() => {
    if (!window.citecheck.sampleData) return
    const off = window.citecheck.onShotState((state) => {
      applyShotState(state, shotState.current)
      requestAnimationFrame(() =>
        requestAnimationFrame(() => window.citecheck.shotReady())
      )
    })
    return off
  }, [])

  // ------------------------------------------------------------ e2e hook
  const e2eRan = useRef(false)
  useEffect(() => {
    const f = window.citecheck.e2eFile
    if (!f || e2eRan.current) return // StrictMode fires effects twice in dev
    e2eRan.current = true
    getInfo().then(() => {
      analyze(f)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const e2eExportDone = useRef(false)

  const openSettings = useCallback(() => {
    settingsFrom.current = screen === 'report' ? 'report' : 'empty'
    morph(() => setScreen('settings'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen])

  // ---------------------------------------------------------------- view
  if (!info) return <div className="h-full" />
  if (screen === 'error') return <ErrorScreen />

  if (screen === 'onboarding') {
    return (
      <Onboarding
        key={onboardStep}
        initialStep={onboardStep}
        prefs={prefs}
        onPrefs={setPrefs}
        onDone={() => morph(() => setScreen('empty'))}
      />
    )
  }

  if (screen === 'settings') {
    return (
      <>
      {credits && (
        <Credits shot={credits === 'shot'} onClose={() => setCredits(false)} />
      )}
      <Settings
        onCredits={() => setCredits('live')}
        key={settingsSection}
        initialSection={settingsSection}
        prefs={prefs}
        onPrefs={setPrefs}
        onBack={() => morph(() => setScreen(settingsFrom.current))}
      />
      </>
    )
  }

  if (screen === 'scanning') {
    return (
      <Scanning
        scanId={scanId}
        name={fileName}
        onCancel={() => {
          scanToken.current = ''
          setScreen('empty')
        }}
      />
    )
  }

  if (screen === 'library' && scan) {
    return (
      <LibraryConfirm
        key={shotLibFilter ?? 'run'}
        initialFilter={shotLibFilter === 'exemplars' ? 'exemplars' : undefined}
        scan={scan}
        libraryDir={scan.library.folder}
        onCancel={reset}
        onVenueChange={setVenue}
        error={jobError}
        onStart={({ paper, links, venue: libVenue, exemplars }) =>
          startJob(paper, {
            library: scan.library.folder,
            links: JSON.stringify(links),
            exemplars: JSON.stringify(exemplars),
            venue: libVenue,
          })
        }
      />
    )
  }

  if (screen === 'running' && jobId) {
    return (
      <Running
        jobId={jobId}
        fileName={fileName}
        onDone={onJobDone}
        onFailed={onJobFailed}
        error={jobError}
        onReset={reset}
        venue={runVenue}
        overrideLayers={shotLayers}
        overrideOutline={shotOutline}
        overrideAnchors={shotAnchors}
      />
    )
  }

  if (screen === 'report' && report && jobId) {
    return (
      <ReportScreen
        key={viewKey ?? jobId}
        report={report}
        overview={lateOverview}
        jobId={jobId}
        externalSelection={extSel}
        externalFilter={extFilter}
        shotPanes={shotPanes}
        registerExport={(fn) => (exportRef.current = fn)}
        prefs={prefs}
        onOpenSettings={openSettings}
        onReset={reset}
        onOpenReport={openReport}
        rebench={rebench}
        onBenchmark={benchmarkReport}
        onExported={(_path) => {
          if (window.citecheck.e2eFile && !e2eExportDone.current) {
            e2eExportDone.current = true
            window.citecheck.e2eDone({ jobId, exportPath: _path })
          }
        }}
      />
    )
  }

  return (
    <Empty
      benchmark={benchmark}
      setBenchmark={setBenchmark}
      venue={venue}
      setVenue={setVenue}
      onFile={analyze}
      onOpenDialog={openDialog}
      libraryDir={libraryDir}
      onPickLibrary={pickLibrary}
      onClearLibrary={() => setLibraryDir(null)}
      onOpenReport={openReport}
      dropError={jobError}
      forceDrag={dragHint}
      prefs={prefs}
      onOpenSettings={openSettings}
    />
  )
}
