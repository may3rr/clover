import { useCallback, useEffect, useRef, useState } from 'react'
import { getInfo, apiFetch } from './lib/api'
import type { Report } from './types/report'
import Empty from './screens/Empty'
import Running, { type LayerUI } from './screens/Running'
import ReportScreen from './screens/ReportScreen'
import ErrorScreen from './screens/Error'
import Settings from './screens/Settings'
import { applyShotState, type ShotCtx } from './lib/shots'
import { morph } from './lib/vt'
import type { Outline, SkAnchor } from './lib/outline'
import { getPrefs, DEFAULT_PREFS, type Prefs } from './lib/prefs'

type Screen = 'empty' | 'running' | 'report' | 'error' | 'settings'

export default function App() {
  const [screen, setScreen] = useState<Screen>('empty')
  const [info, setInfo] = useState<Awaited<
    ReturnType<typeof getInfo>
  > | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [benchmark, setBenchmark] = useState('arxiv_cs_cl')
  const [jobError, setJobError] = useState<string | null>(null)
  const [fileName, setFileName] = useState('paper.docx')
  const exportRef = useRef<(() => void) | null>(null)
  const shotState = useRef<ShotCtx>({})
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS)
  const settingsFrom = useRef<Screen>('empty')
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
    getPrefs().then(setPrefs)
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
  const analyze = useCallback(
    async (path: string) => {
      setJobError(null)
      setFileName(path.split('/').pop() ?? path)
      try {
        const fd = new FormData()
        fd.append('path', path)
        fd.append('benchmark', benchmark)
        const r = await apiFetch('/analyze', { method: 'POST', body: fd })
        if (!r.ok) {
          setJobError('无法读取这个文件。请确认它是 .docx 格式，然后重新拖入。')
          return
        }
        const { job_id } = (await r.json()) as { job_id: string }
        // the front sheet flies into the first skeleton page
        morph(() => {
          setJobId(job_id)
          setScreen('running')
        })
      } catch {
        setJobError('无法连接本地服务。请重新打开应用。')
      }
    },
    [benchmark]
  )

  const openDialog = useCallback(async () => {
    const p = await window.citecheck.openDocxDialog()
    if (p) analyze(p)
  }, [analyze])

  const reset = useCallback(() => {
    setScreen('empty')
    setJobId(null)
    setReport(null)
    setJobError(null)
  }, [])

  // open a past report from the home history — no re-run, no re-upload
  const openReport = useCallback(async (id: string) => {
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
        setReport(rep)
        setScreen('report')
      })
    } catch {
      setJobError('无法连接本地服务。请重新打开应用。')
    }
  }, [])

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
      setReport(rep)
      setScreen('report')
    })
  }, [jobId])

  const onJobFailed = useCallback((error: string) => {
    setJobError(error)
  }, [])

  // -------------------------------------------------------------- menu
  useEffect(() => {
    const offFile = window.citecheck.onOpenFile((p) => {
      if (p.toLowerCase().endsWith('.docx')) analyze(p)
      else setJobError('无法读取这个文件。请确认它是 .docx 格式，然后重新拖入。')
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

  // 导出到 Word is only enabled on the report screen
  useEffect(() => {
    window.citecheck.setMenuState({ exportEnabled: screen === 'report' })
  }, [screen])

  // --------------------------------------------------------- shots hook
  useEffect(() => {
    if (!window.citecheck.shotsMode) return
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
      shotState.current.setSettingsSection = (s) => setSettingsSection(s)
    })
  }, [])
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

  useEffect(() => {
    if (!window.citecheck.shotsMode) return
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

  if (screen === 'settings') {
    return (
      <Settings
        key={settingsSection}
        initialSection={settingsSection}
        prefs={prefs}
        onPrefs={setPrefs}
        onBack={() => morph(() => setScreen(settingsFrom.current))}
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
        overrideLayers={shotLayers}
        overrideOutline={shotOutline}
        overrideAnchors={shotAnchors}
      />
    )
  }

  if (screen === 'report' && report && jobId) {
    return (
      <ReportScreen
        key={jobId}
        report={report}
        jobId={jobId}
        externalSelection={extSel}
        externalFilter={extFilter}
        registerExport={(fn) => (exportRef.current = fn)}
        prefs={prefs}
        onOpenSettings={openSettings}
        onReset={reset}
        onOpenReport={openReport}
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
      onFile={analyze}
      onOpenDialog={openDialog}
      onOpenReport={openReport}
      dropError={jobError}
      forceDrag={dragHint}
      prefs={prefs}
      onOpenSettings={openSettings}
    />
  )
}
