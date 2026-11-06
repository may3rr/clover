// 发送清单: wording for the report's send-list row. Every number comes from
// report.meta.send, which the backend computes from the llm_usage rows
// the run recorded (backend/citecheck/llm/sendlog.py).
import type { SendCategory, SendSummary } from '../types/report'

const UNIT: Record<SendCategory['category'], string> = {
  claim: '句',
  excerpt: '段',
  reference: '条',
  manuscript: '段',
  exemplar: '段',
  other: '项',
}

export const num = (n: number | undefined): string =>
  (n ?? 0).toLocaleString('zh-CN')

/** "正文 12,345 字，发往云端 3,210 字" */
export function sendHeadline(s: SendSummary): string {
  const total = `正文 ${num(s.manuscript_chars)} 字`
  if (!s.requests) return `${total}，没有向云端发送内容`
  return `${total}，发往云端 ${num(s.sent_chars)} 字`
}

/** "论断 12 句" */
export function categoryCount(c: SendCategory): string {
  return `${c.label} ${num(c.count)} ${UNIT[c.category]}`
}

/** "论断 12 句，被引片段 40 段，参考文献 30 条" (categories in backend order) */
export function categoryLine(s: SendSummary): string {
  return (s.categories ?? []).map(categoryCount).join('，')
}

/** Sentence on how much of the manuscript itself left the machine. */
export function manuscriptLine(s: SendSummary): string | null {
  if (!s.requests) return null
  const sent = s.manuscript_sent_chars ?? 0
  if (!sent) return '稿件里的文字没有发往云端。'
  return `其中出自稿件的文字 ${num(sent)} 字，包括带引用的论断句${
    (s.categories ?? []).some((c) => c.category === 'manuscript') ? '和其他正文段落' : ''
  }。`
}

/** What privacy mode did not run, and what to do about it; null when
 * nothing was skipped. */
export function skippedLine(s: SendSummary): string | null {
  const labels = [...new Set((s.skipped ?? []).map((x) => x.label))]
  if (!labels.length) return null
  return `隐私模式跳过了${labels.join('、')}，因为本机没有可用的模型。配置本机模型后重新体检，可以补上这些检查。`
}

/** Tasks that sent one item, plus how often: "支持度判断，发送 2 次". */
export function itemMeta(times: number | undefined, tasks: string[] | undefined): string {
  const t = (tasks ?? []).join('、')
  const n = times ?? 1
  return n > 1 ? `${t}，发送 ${num(n)} 次` : t
}
