// 发送清单: one property row in the report header ("发往云端") that opens
// the list of what this run sent to cloud services. Numbers are the
// backend's record (report.meta.send), never estimates.
import { useState } from 'react'
import type { SendSummary } from '../types/report'
import { ChevronDownIcon } from './Icons'
import {
  categoryCount,
  categoryLine,
  itemMeta,
  manuscriptLine,
  num,
  sendHeadline,
  skippedLine,
} from '../lib/sendList'

export default function SendList({ send }: { send: SendSummary }) {
  const [open, setOpen] = useState(false)
  const cats = send.categories ?? []
  const skipped = skippedLine(send)
  const canOpen = cats.length > 0 || skipped !== null
  return (
    <>
      <button
        className="prop-row send-row"
        aria-expanded={canOpen ? open : undefined}
        disabled={!canOpen}
        onClick={() => setOpen(!open)}
      >
        <span className="prop-label">发往云端</span>
        <span className="prop-value font-normal">{sendHeadline(send)}</span>
        {canOpen && (
          <span className={`send-chev${open ? ' open' : ''}`}>
            <ChevronDownIcon size={13} color="var(--text-secondary)" />
          </span>
        )}
      </button>
      {open && (
        <div className="send-list rise-in">
          {cats.length > 0 && (
            <div className="font-normal">
              {categoryLine(send)}。{manuscriptLine(send)}
            </div>
          )}
          {send.privacy && (
            <div className="font-normal">
              隐私模式已开启，稿件自身的文字只在本机处理。
            </div>
          )}
          {skipped && <div className="font-normal">{skipped}</div>}
          {cats.map((c) => (
            <div key={c.category} className="send-group">
              <div className="t13 secondary font-medium">
                {categoryCount(c)}，共 {num(c.chars)} 字
              </div>
              {(c.items ?? []).map((it, i) => (
                <div key={i} className="send-item">
                  <div className="t13 send-text">
                    {it.chars > it.text.length ? `${it.text}…` : it.text}
                  </div>
                  <div className="t13 secondary">
                    {num(it.chars)} 字，{itemMeta(it.times, it.tasks)}
                  </div>
                </div>
              ))}
              {(c.truncated ?? 0) > 0 && (
                <div className="t13 secondary">
                  另有 {num(c.truncated)} 项未列出，完整记录保存在本机的用量数据库中。
                </div>
              )}
            </div>
          ))}
          {(send.cached_requests ?? 0) + (send.local_requests ?? 0) > 0 && (
            <div className="t13 secondary">
              另有 {num(send.cached_requests)} 次调用使用本机缓存，
              {num(send.local_requests)} 次由本机模型完成，都没有发送内容。
            </div>
          )}
        </div>
      )}
    </>
  )
}
