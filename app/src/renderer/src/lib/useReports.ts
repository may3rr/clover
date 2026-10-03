import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from './api'

/** Sidebar history of finished checks, persisted by the backend
 *  (reports table, id = job id). Shared by the home screen and the
 *  report screen so the sidebar lists the same entries everywhere. */

export interface ReportMeta {
  id: string
  filename: string
  title: string
  created_at: string
  n_high: number
  n_medium: number
  n_low: number
}

const SHOT_HISTORY: ReportMeta[] = [
  {
    id: 'shot-1',
    filename: 'numeric_en.docx',
    title: 'Citation Behaviour in Neural Models',
    created_at: new Date(Date.now() - 86400000).toISOString(),
    n_high: 3,
    n_medium: 11,
    n_low: 1,
  },
  {
    id: 'shot-2',
    filename: 'hallucination_survey.docx',
    title: 'A Survey of Hallucination',
    created_at: new Date(Date.now() - 3 * 86400000).toISOString(),
    n_high: 1,
    n_medium: 6,
    n_low: 2,
  },
  {
    id: 'shot-3',
    filename: 'retrieval_paper.docx',
    title: 'Dense Passage Retrieval',
    created_at: new Date(Date.now() - 9 * 86400000).toISOString(),
    n_high: 0,
    n_medium: 4,
    n_low: 3,
  },
]

export function useReports(): {
  reports: ReportMeta[]
  remove: (id: string) => void
} {
  const [reports, setReports] = useState<ReportMeta[]>([])

  useEffect(() => {
    if (window.citecheck.shotsMode) {
      setReports(SHOT_HISTORY)
      return
    }
    apiFetch('/reports')
      .then((r) => r.json())
      .then((h: ReportMeta[]) => setReports(Array.isArray(h) ? h : []))
      .catch(() => setReports([]))
  }, [])

  const remove = useCallback((id: string) => {
    setReports((h) => h.filter((r) => r.id !== id))
    if (window.citecheck.shotsMode) return
    apiFetch(`/reports/${id}`, { method: 'DELETE' }).catch(() => {})
  }, [])

  return { reports, remove }
}
