/** Scripted walkthroughs of the real UI for video capture.
 *
 *  A tour moves a visible macOS cursor to real elements and clicks them, so
 *  every transition on screen is the app's own. Run one with
 *  `app.html?tour=<name>` (see TOURS) or `window.clover.play(name)`; the
 *  recorder (site/scripts/record.mjs) waits for `window.clover.tourDone`. */
import { flags, go } from './mock'

type Target = string | { sel: string; text?: string; nth?: number }
export type Step =
  | { go: string }
  | { click: Target; pause?: number }
  | { hover: Target; pause?: number }
  | { scroll: Target; by: number; ms?: number }
  | { reveal: string; ms?: number }
  | { type: Target; text: string; pause?: number }
  | { wait: number }
  | { cursor: 'show' | 'hide' }

const row = (text: string): Target => ({ sel: '.list-row', text })
const side = (text: string): Target => ({ sel: '.side-row', text })
const back: Target = { sel: '.detail-in .link-accent' }
const reading = '.paper'
/** the venue review card in the reading area (OverviewCard) */
export const OVERVIEW_CARD = 'section[aria-label$="对标"]'

/** Scenes for the product video; each also stands alone. */
export const TOURS: Record<string, Step[]> = {
  // 首次启动引导：圆点聚成环 -> 连接模型 -> 名字与头像 -> 隐私说明 -> 首页
  onboarding: [
    { go: 'onboarding-intro' },
    { cursor: 'hide' },
    { wait: 3600 },
    { cursor: 'show' },
    { click: { sel: '.pill-accent', text: '开始设置' }, pause: 2400 },
    { hover: '.onboard-model', pause: 1200 },
    { click: { sel: '.onboard-model .pill-accent', text: '保存并继续' }, pause: 1400 },
    { type: '.account-name-input', text: '李明', pause: 600 },
    { click: { sel: '.swatch', nth: 3 }, pause: 500 },
    { click: { sel: '.swatch', nth: 1 }, pause: 900 },
    { click: { sel: '.pill-accent', text: '继续' }, pause: 2400 },
    { click: '.onboard-consent', pause: 900 },
    { click: { sel: '.pill-accent', text: '开始使用' }, pause: 1800 },
  ],
  // 拖入论文 -> 体检中 -> 报告
  check: [
    { go: 'empty' },
    { wait: 900 },
    { click: { sel: '.pill-accent', text: '选择文件' }, pause: 200 },
    { cursor: 'hide' },
    { wait: 10500 },
    { cursor: 'show' },
    { hover: row('未能在数据库中找到'), pause: 1200 },
  ],
  authenticity: [
    { go: 'report' },
    { wait: 700 },
    { click: side('文献真实性'), pause: 900 },
    { click: row('未能在数据库中找到'), pause: 3200 },
    { click: back, pause: 600 },
    { click: row('文献信息与数据库记录不一致'), pause: 3200 },
    { click: back, pause: 600 },
  ],
  support: [
    { go: 'report' },
    { wait: 700 },
    { click: side('论断支持度'), pause: 900 },
    { click: row('不支持这条论断'), pause: 3600 },
    { scroll: '.detail-in .overflow-y-auto', by: 320, ms: 1400 },
    { wait: 1600 },
    { click: back, pause: 600 },
    { click: row('可能引错了文献'), pause: 3600 },
    { click: back, pause: 600 },
  ],
  distribution: [
    { go: 'report' },
    { wait: 700 },
    { click: side('引用分布'), pause: 900 },
    { click: row('引用分布偏离'), pause: 3600 },
    { click: back, pause: 600 },
    { click: row('同时引用了'), pause: 3000 },
    { click: back, pause: 600 },
  ],
  norms: [
    { go: 'report' },
    { wait: 700 },
    { click: side('格式规范'), pause: 900 },
    { click: row('建议修订'), pause: 3200 },
    { click: back, pause: 600 },
  ],
  overview: [
    { go: 'report' },
    { wait: 900 },
    { reveal: OVERVIEW_CARD, ms: 1600 },
    { wait: 3600 },
    { scroll: reading, by: -2000, ms: 1200 },
  ],
  export: [
    { go: 'report' },
    { wait: 900 },
    { click: { sel: 'button', text: '导出到 Word' }, pause: 3200 },
  ],
  settings: [
    { go: 'settings-model' },
    { wait: 2400 },
    { click: { sel: 'button', text: '用量与费用' }, pause: 2600 },
  ],
}
TOURS.full = [
  ...TOURS.onboarding,
  ...TOURS.check.slice(1),
  ...TOURS.authenticity.slice(2),
  ...TOURS.support.slice(2),
  ...TOURS.distribution.slice(2),
  ...TOURS.norms.slice(2),
  { click: side('全部问题'), pause: 600 },
  ...TOURS.overview.slice(1),
  ...TOURS.export.slice(1),
]

// ----------------------------------------------------------------- cursor
let cursor: HTMLDivElement | null = null
let pos = { x: 640, y: 560 }
function ensureCursor(): HTMLDivElement {
  if (cursor) return cursor
  cursor = document.createElement('div')
  cursor.className = 'tour-cursor'
  cursor.innerHTML = `<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
    <path d="M5 2.5v19.2l4.6-4.4 3.1 6.9 3.4-1.5-3.1-6.8h6.4z" fill="#000" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/>
  </svg><span class="tour-ripple"></span>`
  document.body.appendChild(cursor)
  place(pos.x, pos.y, 0)
  return cursor
}
function place(x: number, y: number, ms: number) {
  const c = ensureCursor()
  c.style.transition = `transform ${ms}ms cubic-bezier(0.45, 0, 0.2, 1)`
  c.style.transform = `translate(${x}px, ${y}px)`
  pos = { x, y }
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function resolve(t: Target): HTMLElement | null {
  const spec = typeof t === 'string' ? { sel: t } : t
  let els = Array.from(document.querySelectorAll<HTMLElement>(spec.sel))
  if (spec.text) els = els.filter((e) => e.textContent?.includes(spec.text!))
  els = els.filter((e) => e.getBoundingClientRect().width > 0)
  return els[spec.nth ?? 0] ?? null
}
async function find(t: Target, timeout = 4000): Promise<HTMLElement> {
  const t0 = performance.now()
  for (;;) {
    const el = resolve(t)
    if (el) return el
    if (performance.now() - t0 > timeout) throw new Error(`tour: no target ${JSON.stringify(t)}`)
    await sleep(50)
  }
}
async function moveTo(el: HTMLElement) {
  el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  await sleep(120)
  const r = el.getBoundingClientRect()
  const x = r.left + Math.min(r.width / 2, 120)
  const y = r.top + r.height / 2
  const ms = Math.min(900, Math.max(380, Math.hypot(x - pos.x, y - pos.y) * 1.1))
  place(x, y, ms)
  await sleep(ms + 60)
}

/** Scroll the reading area so `sel` sits near its top. */
export async function reveal(sel: string, ms = 900): Promise<void> {
  const el = await find(sel)
  const pane = el.closest<HTMLElement>(reading)
  if (!pane) return
  const top =
    el.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop - 72
  pane.scrollTo({ top, behavior: 'smooth' })
  await sleep(ms)
}

// ------------------------------------------------------------------- run
export async function play(steps: Step[] | string): Promise<void> {
  const list = typeof steps === 'string' ? TOURS[steps] : steps
  if (!list) throw new Error(`tour: unknown ${steps}`)
  flags.quietExport = true
  ensureCursor().style.opacity = '1'
  try {
    await run(list)
  } finally {
    flags.quietExport = false
    // visitors click on after a tour; a frozen fake cursor would mislead
    const c = ensureCursor()
    setTimeout(() => (c.style.opacity = '0'), 900)
  }
}

async function run(list: Step[]) {
  for (const s of list) {
    if ('go' in s) await go(s.go)
    else if ('wait' in s) await sleep(s.wait)
    else if ('cursor' in s) ensureCursor().style.opacity = s.cursor === 'show' ? '1' : '0'
    else if ('hover' in s) {
      await moveTo(await find(s.hover))
      await sleep(s.pause ?? 400)
    } else if ('click' in s) {
      const el = await find(s.click)
      await moveTo(el)
      const c = ensureCursor()
      c.classList.remove('press')
      void c.offsetWidth
      c.classList.add('press')
      await sleep(110)
      el.click()
      await sleep(s.pause ?? 500)
    } else if ('type' in s) {
      const el = (await find(s.type)) as HTMLInputElement
      await moveTo(el)
      el.focus()
      // React tracks the value through the native setter, so set it there
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
      const put = (v: string) => {
        set.call(el, v)
        el.dispatchEvent(new Event('input', { bubbles: true }))
      }
      put('')
      await sleep(300)
      for (let i = 1; i <= s.text.length; i++) {
        put(s.text.slice(0, i))
        await sleep(180)
      }
      el.blur()
      await sleep(s.pause ?? 400)
    } else if ('reveal' in s) {
      await reveal(s.reveal, s.ms)
    } else if ('scroll' in s) {
      const el = await find(s.scroll)
      el.scrollBy({ top: s.by, behavior: 'smooth' })
      await sleep(s.ms ?? 1000)
    }
  }
}
