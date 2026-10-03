import { useRef, useState } from 'react'
import { DocTextFillIcon, TrashFillIcon, LayerTile } from './Icons'
import { relDay } from '../lib/reltime'
import type { ReportMeta } from '../lib/useReports'

/** One past-check entry in the sidebar. Two-tap delete: the first click
 *  arms a 删除 confirm for 3s, the second actually removes the record. */
export default function HistoryRow({
  meta,
  active = false,
  onOpen,
  onDelete,
}: {
  meta: ReportMeta
  active?: boolean
  onOpen: () => void
  onDelete: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const arm = (e: React.MouseEvent) => {
    e.stopPropagation()
    setConfirming(true)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setConfirming(false), 3000)
  }
  const confirm = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (timer.current) clearTimeout(timer.current)
    onDelete()
  }

  return (
    <button
      className={`hist-row${active ? ' sel' : ''}`}
      onClick={active ? undefined : onOpen}
    >
      <span className="hist-row-main min-w-0">
        <LayerTile size={20} icon={<DocTextFillIcon size={12} />} />
        <span className="min-w-0">
          <span className="hist-row-name">{meta.filename}</span>
          <span className="t13 secondary hist-row-sub">
            {relDay(meta.created_at)}
            {meta.n_high > 0 && ` · ${meta.n_high} 严重`}
          </span>
        </span>
      </span>
      {confirming ? (
        <span
          className="t13 hist-row-del confirming"
          role="button"
          tabIndex={0}
          onClick={confirm}
          onKeyDown={(e) => e.key === 'Enter' && confirm(e as never)}
        >
          删除
        </span>
      ) : (
        <span
          className="hist-row-del"
          role="button"
          tabIndex={0}
          aria-label={`删除 ${meta.filename} 的检查记录`}
          onClick={arm}
          onKeyDown={(e) => e.key === 'Enter' && arm(e as never)}
        >
          <TrashFillIcon size={13} color="var(--text-secondary)" />
        </span>
      )}
    </button>
  )
}
