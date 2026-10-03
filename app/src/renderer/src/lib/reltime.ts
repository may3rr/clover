/** Relative date labels for the history list: 今天 14:20 / 昨天 14:20 /
 *  10月3日 / 2025年10月3日. Input is a local ISO timestamp (backend writes
 *  datetime.now().isoformat), parsed as local time. */

function hm(d: Date): string {
  return `${String(d.getHours()).padStart(2, '0')}:${String(
    d.getMinutes()
  ).padStart(2, '0')}`
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

export function relDay(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  if (sameDay(d, now)) return `今天 ${hm(d)}`
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (sameDay(d, yesterday)) return `昨天 ${hm(d)}`
  const md = `${d.getMonth() + 1} 月 ${d.getDate()} 日`
  if (d.getFullYear() === now.getFullYear()) return md
  return `${d.getFullYear()} 年 ${md}`
}
