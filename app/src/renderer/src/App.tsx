import { useCallback, useEffect, useRef, useState } from 'react'
import { getInfo, apiFetch } from './lib/api'
import type { Report } from './types/report'
import Empty from './screens/Empty'
import Running, { type LayerUI } from './screens/Running'
import ReportScreen from './screens/ReportScreen'
import ErrorScreen from './screens/Error'
import { applyShotState, type ShotCtx } from './lib/shots'

type Screen = 'empty' | 'running' | 'report' | 'error'

export default function App() {
  const [screen, setScreen] = useState<Screen>('empty')
  const [info, setInfo] = useState<Awaited<
    ReturnType<typeof getInfo>
  > | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [benchmark, setBenchmark] = useState('arxiv_cs_cl')
  const [jobError, setJobError] = useState<string | null>(null)
  const exportRef = useRef<(() => void) | null>(null)
  const shotState = useRef<ShotCtx>({})

  // ---------------------------------------------------------------- boot
  useEffect(() => {
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
        setJobId(job_id)
        setScreen('running')
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

  // ------------------------------------------------------- job lifecycle
  const onJobDone = useCallback(async () => {
    if (!jobId) return
    const r = await apiFetch(`/jobs/${jobId}/report`)
    if (!r.ok) {
      setJobError('读取报告失败。请重新体检。')
      return
    }
    setReport((await r.json()) as Report)
    setScreen('report')
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
      shotState.current.report = r as Report
      shotState.current.setScreen = setScreen
      shotState.current.setReport = setReport
      shotState.current.setLayers = (l) => setShotLayers(l)
      shotState.current.selectItem = (id) => shotSelect.current?.(id)
      shotState.current.setDrag = (v) => setDragHint(v)
    })
  }, [])
  const [shotLayers, setShotLayers] = useState<LayerUI | null>(null)
  const [dragHint, setDragHint] = useState(false)
  const shotSelect = useRef<((id: string | null) => void) | null>(null)

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
  useEffect(() => {
    const f = window.citecheck.e2eFile
    if (!f) return
    getInfo().then(() => {
      analyze(f)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const e2eExportDone = useRef(false)

  // ---------------------------------------------------------------- view
  if (!info) return <div className="h-full" />
  if (screen === 'error') return <ErrorScreen />

  if (screen === 'running' && jobId) {
    return (
      <Running
        jobId={jobId}
        onDone={onJobDone}
        onFailed={onJobFailed}
        error={jobError}
        onReset={reset}
        overrideLayers={shotLayers}
      />
    )
  }

  if (screen === 'report' && report && jobId) {
    return (
      <ReportScreen
        report={report}
        jobId={jobId}
        registerExport={(fn) => (exportRef.current = fn)}
        registerSelect={(fn) => (shotSelect.current = fn)}
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
      dropError={jobError}
      forceDrag={dragHint}
    />
  )
}
