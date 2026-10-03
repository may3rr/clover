import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../lib/api'
import {
  commentAuthor,
  commentInitials,
  putPrefs,
  type Prefs,
} from '../lib/prefs'
import Avatar from '../components/Avatar'
import { pickGreeting } from '../lib/greetings'
import {
  ChevronLeftIcon,
  PersonFillIcon,
  QuoteBubbleFillIcon,
  GearshapeFillIcon,
  ChartBarFillIcon,
  InfoCircleFillIcon,
  LayerTile,
  PageIcon,
  GitHubMarkIcon,
} from '../components/Icons'
import AccountChip from '../components/AccountChip'
import { CREDITS, GITHUB_URL } from '../lib/credits'
import { APP_NAME } from '../lib/brand'
import {
  BrandIcon,
  QwenIcon,
  OpenAIIcon,
  DeepSeekIcon,
} from '../components/BrandIcons'
import { BRAND_PATHS } from '../components/brandPaths'

/** Left-nav pane + grouped fields, in the style of macOS Settings. */

export type Section = 'account' | 'comments' | 'model' | 'usage' | 'about'
const SECTIONS: {
  id: Section
  label: string
  color: string
  icon: React.ReactNode
}[] = [
  {
    id: 'account',
    label: '账户',
    color: 'var(--tile-blue)',
    icon: <PersonFillIcon size={13} />,
  },
  {
    id: 'comments',
    label: '批注署名',
    color: 'var(--tile-teal)',
    icon: <QuoteBubbleFillIcon size={13} />,
  },
  {
    id: 'model',
    label: '模型',
    color: 'var(--tile-grey)',
    icon: <GearshapeFillIcon size={13} />,
  },
  {
    id: 'usage',
    label: '用量与费用',
    color: 'var(--tile-purple)',
    icon: <ChartBarFillIcon size={13} />,
  },
  {
    id: 'about',
    label: '关于',
    color: 'var(--tile-indigo)',
    icon: <InfoCircleFillIcon size={13} />,
  },
]

const AVATAR_COLORS = ['blue', 'teal', 'indigo', 'purple', 'grey'] as const

const TASK_FIELDS: { key: string; label: string }[] = [
  { key: 'judge', label: '支持度判断' },
  { key: 'review', label: '深度复核' },
  { key: 'review_fallback', label: '复核兜底' },
  { key: 'extract', label: '论断抽取' },
  { key: 'typo', label: '错别字' },
  { key: 'structure', label: '字段补全' },
  { key: 'function', label: '引用功能' },
]

interface ModelCfg {
  base_url: string
  has_api_key: boolean
  models: Record<string, string>
}

interface UsageRow {
  day?: string
  provider?: string
  model?: string
  doc?: string
  calls: number
  cached_calls: number
  prompt: number
  completion: number
  cost: number | null
}
interface Usage {
  by_doc: UsageRow[]
  by_provider: UsageRow[]
  by_day: UsageRow[]
  totals: UsageRow[]
}

function yuan(v: number | null): string {
  if (v === null) return '—'
  if (v > 0 && v < 0.01) return '<0.01'
  return v.toFixed(2)
}

function rowTokens(r: UsageRow): number {
  return (r.prompt ?? 0) + (r.completion ?? 0)
}

function tokens(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)} 万`
  if (n >= 1000) return `${(n / 1000).toFixed(1)} 千`
  return String(n)
}

/** Downscale a picked image to a <=128px square PNG data URL. */
function downscale(dataUrl: string): Promise<string> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const s = Math.min(img.width, img.height)
      const cv = document.createElement('canvas')
      cv.width = cv.height = 128
      const ctx = cv.getContext('2d')
      if (!ctx) return resolve(dataUrl)
      ctx.drawImage(
        img,
        (img.width - s) / 2,
        (img.height - s) / 2,
        s,
        s,
        0,
        0,
        128,
        128
      )
      resolve(cv.toDataURL('image/png'))
    }
    img.onerror = () => resolve(dataUrl)
    img.src = dataUrl
  })
}

export default function Settings({
  prefs,
  onPrefs,
  onBack,
  onCredits,
  initialSection = 'account',
}: {
  prefs: Prefs
  onPrefs: (p: Prefs) => void
  onBack: () => void
  onCredits: () => void
  initialSection?: Section
}) {
  const [sec, setSec] = useState<Section>(initialSection)
  const [savedAt, setSavedAt] = useState(0)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const update = useCallback(
    (patch: Partial<Prefs>) => {
      const next = { ...prefs, ...patch }
      onPrefs(next)
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(() => {
        putPrefs(next)
          .then(() => setSavedAt(Date.now()))
          .catch(() => {})
      }, 400)
    },
    [prefs, onPrefs]
  )

  const pickImage = async () => {
    const small = await pickAvatarImage()
    if (!small) return
    update({ avatar: { kind: 'image', color: prefs.avatar.color, image: small } })
  }

  return (
    <div className="relative h-full overflow-hidden">
      {/* same pane as the report/home sidebar, so switching screens
          doesn't shift the chrome */}
      <aside className="glass-sidebar flex flex-col">
        <div className="drag-strip" style={{ height: 52, flex: 'none' }} />
        <div className="group-label" style={{ fontWeight: 600 }}>
          设置
        </div>
        <nav className="flex-1 flex flex-col" style={{ padding: '0 8px' }}>
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className={`side-row${sec === s.id ? ' sel' : ''}`}
              onClick={() => setSec(s.id)}
            >
              <LayerTile size={20} color={s.color} icon={s.icon} />
              <span className="font-normal">{s.label}</span>
            </button>
          ))}
        </nav>
        <div style={{ padding: '0 12px 12px' }}>
          <AccountChip prefs={prefs} onOpen={() => setSec('account')} />
        </div>
      </aside>
      <div
        className="flex flex-col h-full"
        style={{ marginLeft: 240, background: 'var(--bg)' }}
      >
        <header
          className="drag-strip bar-solid strip-edge flex items-center"
          style={{ height: 52, flex: 'none', padding: '0 24px', gap: 12 }}
        >
          <button
            className="pill flex items-center gap-1"
            style={{ padding: '4px 12px' }}
            onClick={onBack}
          >
            <ChevronLeftIcon size={13} color="var(--text-secondary)" />
            <span className="font-normal">返回</span>
          </button>
          <div className="flex-1" />
          {savedAt > 0 && <span className="t13 secondary">已保存</span>}
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="settings-col">
            {sec === 'account' && (
              <AccountSection
                prefs={prefs}
                update={update}
                pickImage={pickImage}
              />
            )}
            {sec === 'comments' && (
              <CommentsSection prefs={prefs} update={update} />
            )}
            {sec === 'model' && <ModelSection />}
            {sec === 'usage' && <UsageSection />}
            {sec === 'about' && <AboutSection onCredits={onCredits} />}
          </div>
        </main>
      </div>
    </div>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="field">
      <label className="field-label">{label}</label>
      {children}
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  )
}

/** avatar + name + colour swatches — shared by Settings and onboarding */
export function ProfileEditor({
  prefs,
  update,
  pickImage,
}: {
  prefs: Prefs
  update: (p: Partial<Prefs>) => void
  pickImage: () => void
}) {
  return (
    <div className="account-hero">
      <button
        className="avatar-btn"
        onClick={pickImage}
        title="上传头像图片"
      >
        <Avatar prefs={prefs} size={72} />
      </button>
      <input
        className="account-name-input"
        value={prefs.name}
        placeholder="你的名字"
        onChange={(e) => update({ name: e.target.value })}
      />
      <div className="swatches">
        {AVATAR_COLORS.map((c) => {
          const on =
            prefs.avatar.kind === 'color' && prefs.avatar.color === c
          return (
            <button
              key={c}
              className="swatch"
              style={{ background: `var(--tile-${c})` }}
              aria-label={c}
              onClick={() =>
                update({ avatar: { kind: 'color', color: c, image: null } })
              }
            >
              {on && (
                <svg
                  width={12}
                  height={12}
                  viewBox="0 0 12 12"
                  fill="none"
                  stroke="white"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M2.5 6.5 5 9 9.5 3.5" />
                </svg>
              )}
            </button>
          )
        })}
      </div>
      {prefs.avatar.kind === 'image' && (
        <button
          className="t13 secondary avatar-remove"
          onClick={() =>
            update({ avatar: { ...prefs.avatar, kind: 'color', image: null } })
          }
        >
          移除图片，改用颜色头像
        </button>
      )}
    </div>
  )
}

/** native picker → downscaled data URL, or null when cancelled */
export async function pickAvatarImage(): Promise<string | null> {
  const raw = await window.citecheck.pickAvatar().catch(() => null)
  return raw ? downscale(raw) : null
}

function AccountSection({
  prefs,
  update,
  pickImage,
}: {
  prefs: Prefs
  update: (p: Partial<Prefs>) => void
  pickImage: () => void
}) {
  const [hello] = useState(() => pickGreeting(prefs.name))
  const [days, setDays] = useState<Map<string, number> | null>(null)
  useEffect(() => {
    const merge = (u: Usage) => {
      const m = new Map<string, number>()
      for (const r of u.by_day) {
        if (r.day) m.set(r.day, (m.get(r.day) ?? 0) + r.calls)
      }
      if (window.citecheck.shotsMode) {
        for (const [d, n] of SHOT_ACTIVITY) m.set(d, (m.get(d) ?? 0) + n)
      }
      setDays(m)
    }
    if (window.citecheck.shotsMode) {
      merge(SHOT_USAGE)
      return
    }
    apiFetch('/usage')
      .then((r) => r.json())
      .then(merge)
      .catch(() => setDays(new Map()))
  }, [])

  return (
    <>
      <h2 className="t26 account-hello">{hello}</h2>
      <ProfileEditor prefs={prefs} update={update} pickImage={pickImage} />

      <div className="account-activity">
        {days && <ActivityCard days={days} />}
      </div>
    </>
  )
}

const WEEKS = 26

/** GitHub-style activity grid: one cell per day, Monday-first weeks,
 *  intensity from model-call count. Month labels sit above the week
 *  column where the month changes; the year shows on the first label
 *  and whenever it rolls over. */
function ActivityCard({ days }: { days: Map<string, number> }) {
  const today = new Date()
  const todayKey = keyOf(today)
  // Monday of this week, then back WEEKS-1 more weeks
  const mondayOffset = (today.getDay() + 6) % 7
  const start = new Date(today)
  start.setDate(start.getDate() - mondayOffset - (WEEKS - 1) * 7)

  const cells: { date: Date; key: string; calls: number }[] = []
  const cursor = new Date(start)
  while (keyOf(cursor) <= todayKey) {
    const k = keyOf(cursor)
    cells.push({ date: new Date(cursor), key: k, calls: days.get(k) ?? 0 })
    cursor.setDate(cursor.getDate() + 1)
  }
  const max = Math.max(...cells.map((c) => c.calls), 1)
  const activeDays = cells.filter((c) => c.calls > 0).length
  let streak = 0
  for (let i = cells.length - 1; i >= 0; i--) {
    // today without activity yet doesn't break the streak
    if (cells[i].calls === 0 && i === cells.length - 1) continue
    if (cells[i].calls === 0) break
    streak++
  }

  const nCols = Math.ceil(cells.length / 7)
  const monthLabels: (string | null)[] = []
  for (let w = 0; w < nCols; w++) {
    const first = cells[w * 7]
    const prev = w > 0 ? cells[(w - 1) * 7] : null
    if (!first) {
      monthLabels.push(null)
    } else if (!prev || first.date.getMonth() !== prev.date.getMonth()) {
      // year only on the rollover label — the first label sits too close
      // to the next month for the long form
      const rollover =
        prev && first.date.getFullYear() !== prev.date.getFullYear()
      monthLabels.push(
        rollover
          ? `${first.date.getFullYear()} 年 ${first.date.getMonth() + 1} 月`
          : `${first.date.getMonth() + 1} 月`
      )
    } else {
      monthLabels.push(null)
    }
  }

  return (
    <>
      <div className="act-months" aria-hidden>
        {monthLabels.map((label, i) => (
          <div key={i} className="t13 secondary act-month">
            {label}
          </div>
        ))}
      </div>
      <div className="act-grid" role="img" aria-label="体检活动热力图">
        {cells.map((c) => {
          const label = `${c.date.getFullYear()} 年 ${c.date.getMonth() + 1} 月 ${c.date.getDate()} 日`
          return (
            <div
              key={c.key}
              className="act-cell"
              title={`${label}：${c.calls ? `${c.calls} 次调用` : '没有活动'}`}
              style={
                c.calls === 0
                  ? undefined
                  : {
                      background: 'var(--accent)',
                      opacity: 0.3 + 0.7 * Math.cbrt(c.calls / max),
                    }
              }
            />
          )
        })}
      </div>
      <div className="t13 secondary act-summary">
        过去 {WEEKS} 周活跃 {activeDays} 天
        {streak >= 2 ? `，最近连续 ${streak} 天` : ''}
      </div>
    </>
  )
}

function keyOf(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** Extra history only for screenshot mode, so the activity grid is not
 *  confined to the two weeks SHOT_USAGE covers. */
const SHOT_ACTIVITY: [string, number][] = [
  ['2026-06-15', 9],
  ['2026-06-24', 14],
  ['2026-07-02', 6],
  ['2026-07-18', 22],
  ['2026-07-21', 11],
  ['2026-08-05', 17],
  ['2026-08-19', 8],
  ['2026-08-27', 25],
  ['2026-09-03', 12],
  ['2026-09-10', 30],
  ['2026-09-11', 16],
  ['2026-09-19', 7],
]

function CommentsSection({
  prefs,
  update,
}: {
  prefs: Prefs
  update: (p: Partial<Prefs>) => void
}) {
  const author = commentAuthor(prefs)
  const initials = commentInitials(prefs)
  return (
    <>
      <h2 className="t20 settings-h">批注署名</h2>
      <div className="group-label">导出到 Word 的批注会用这个署名</div>
      <div className="card">
        <Field label="署名" hint="留空时与账户名字一致">
          <input
            className="field-input"
            value={prefs.comment_author}
            placeholder={prefs.name || APP_NAME}
            onChange={(e) => update({ comment_author: e.target.value })}
          />
        </Field>
        <Field label="缩写" hint="Word 在批注里显示的头像文字，留空自动生成">
          <input
            className="field-input"
            value={prefs.comment_initials}
            placeholder={initials}
            onChange={(e) => update({ comment_initials: e.target.value })}
          />
        </Field>
      </div>
      <div className="group-label">预览</div>
      <div className="card cmt-preview">
        <div
          className="cmt-avatar"
          style={{ background: `var(--tile-${prefs.avatar.color})` }}
        >
          {initials || '引'}
        </div>
        <div className="min-w-0">
          <div className="cmt-author">
            {author}
            <span className="t13 secondary cmt-time">现在</span>
          </div>
          <div className="cmt-body">
            这条批注会带着你的名字和缩写，出现在导出的 Word 里。
          </div>
        </div>
      </div>
    </>
  )
}

const SHOT_CFG: ModelCfg = {
  base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  has_api_key: true,
  models: {
    judge: 'qwen3.8-flash',
    review: 'qwen3.8-max',
    review_fallback: 'qwen3.7-max',
    extract: 'qwen3.7-flash',
    typo: 'qwen3.8-flash',
    structure: 'qwen3.7-flash',
    function: 'qwen3.7-flash',
  },
}

const SHOT_USAGE: Usage = {
  by_doc: [
    {
      doc: 'hallucination_survey.docx',
      model: 'qwen3.8-flash',
      calls: 42,
      cached_calls: 0,
      prompt: 168000,
      completion: 21000,
      cost: 0.1911,
    },
    {
      doc: 'hallucination_survey.docx',
      model: 'qwen3.8-max',
      calls: 4,
      cached_calls: 0,
      prompt: 12000,
      completion: 1600,
      cost: 0.2016,
    },
    {
      doc: 'hallucination_survey.docx',
      model: 'qwen3.7-flash',
      calls: 47,
      cached_calls: 6,
      prompt: 33000,
      completion: 5200,
      cost: 0.0108,
    },
    {
      doc: 'retrieval_paper.docx',
      model: 'qwen3.8-flash',
      calls: 38,
      cached_calls: 0,
      prompt: 151000,
      completion: 19000,
      cost: 0.1721,
    },
  ],
  by_provider: [
    {
      provider: 'dashscope',
      model: 'qwen3.8-flash',
      calls: 80,
      cached_calls: 0,
      prompt: 319000,
      completion: 40000,
      cost: 0.3632,
    },
    {
      provider: 'dashscope',
      model: 'qwen3.8-max',
      calls: 4,
      cached_calls: 0,
      prompt: 12000,
      completion: 1600,
      cost: 0.2016,
    },
    {
      provider: 'dashscope',
      model: 'qwen3.7-flash',
      calls: 47,
      cached_calls: 6,
      prompt: 33000,
      completion: 5200,
      cost: 0.0108,
    },
  ],
  by_day: [
    { day: '2026-09-25', model: 'qwen3.7-flash', calls: 12, cached_calls: 2,
      prompt: 9000, completion: 1400, cost: 0.003 },
    { day: '2026-09-26', model: 'qwen3.8-flash', calls: 20, cached_calls: 0,
      prompt: 76000, completion: 9500, cost: 0.086 },
    { day: '2026-09-28', model: 'qwen3.8-flash', calls: 8, cached_calls: 1,
      prompt: 31000, completion: 3800, cost: 0.035 },
    { day: '2026-09-30', model: 'qwen3.7-flash', calls: 15, cached_calls: 3,
      prompt: 11000, completion: 1700, cost: 0.004 },
    { day: '2026-10-01', model: 'qwen3.8-flash', calls: 26, cached_calls: 0,
      prompt: 98000, completion: 12000, cost: 0.111 },
    { day: '2026-10-02', model: 'qwen3.8-flash', calls: 31, cached_calls: 2,
      prompt: 118000, completion: 14500, cost: 0.134 },
    { day: '2026-10-03', model: 'qwen3.8-flash', calls: 44, cached_calls: 0,
      prompt: 166000, completion: 20500, cost: 0.188 },
    { day: '2026-10-04', model: 'qwen3.7-flash', calls: 18, cached_calls: 4,
      prompt: 13000, completion: 2000, cost: 0.005 },
    { day: '2026-10-05', model: 'qwen3.8-flash', calls: 55, cached_calls: 1,
      prompt: 205000, completion: 26000, cost: 0.232 },
    { day: '2026-10-06', model: 'qwen3.8-flash', calls: 80, cached_calls: 0,
      prompt: 319000, completion: 40000, cost: 0.3632 },
    { day: '2026-10-06', model: 'qwen3.7-flash', calls: 47, cached_calls: 6,
      prompt: 33000, completion: 5200, cost: 0.0108 },
  ],
  totals: [
    {
      model: 'qwen3.8-flash',
      calls: 80,
      cached_calls: 0,
      prompt: 319000,
      completion: 40000,
      cost: 0.3632,
    },
    {
      model: 'qwen3.8-max',
      calls: 4,
      cached_calls: 0,
      prompt: 12000,
      completion: 1600,
      cost: 0.2016,
    },
    {
      model: 'qwen3.7-flash',
      calls: 47,
      cached_calls: 6,
      prompt: 33000,
      completion: 5200,
      cost: 0.0108,
    },
  ],
}

/** right-aligned secondary figures, spaced apart instead of joined by dots */
function Stats({ parts }: { parts: string[] }) {
  return (
    <span className="t13 secondary flex" style={{ gap: 16, flex: 'none' }}>
      {parts.map((p, i) => (
        <span key={i} style={{ fontVariantNumeric: 'tabular-nums' }}>
          {p}
        </span>
      ))}
    </span>
  )
}

function providerName(id: string): string {
  return PRESETS.find((p) => p.id === id)?.name ?? id
}

type ProviderKey = 'dashscope' | 'openai' | 'deepseek'

interface Preset {
  id: ProviderKey
  name: string
  base: string
  models: Record<string, string>
}

const PRESETS: Preset[] = [
  {
    id: 'dashscope',
    name: '阿里云百炼',
    base: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: {
      judge: 'qwen3.8-flash',
      review: 'qwen3.8-max',
      review_fallback: 'qwen3.7-max',
      extract: 'qwen3.7-flash',
      typo: 'qwen3.8-flash',
      structure: 'qwen3.7-flash',
      function: 'qwen3.7-flash',
    },
  },
  {
    id: 'openai',
    name: 'OpenAI',
    base: 'https://api.openai.com/v1',
    models: {
      judge: 'gpt-4o-mini',
      review: 'gpt-4o',
      review_fallback: 'gpt-4o-mini',
      extract: 'gpt-4o-mini',
      typo: 'gpt-4o-mini',
      structure: 'gpt-4o-mini',
      function: 'gpt-4o-mini',
    },
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    base: 'https://api.deepseek.com/v1',
    models: {
      judge: 'deepseek-chat',
      review: 'deepseek-reasoner',
      review_fallback: 'deepseek-chat',
      extract: 'deepseek-chat',
      typo: 'deepseek-chat',
      structure: 'deepseek-chat',
      function: 'deepseek-chat',
    },
  },
]

interface CustomProvider {
  name: string
  base: string
  icon: string
}

const providerStore = {
  load(): { sel?: string; customs?: CustomProvider[] } {
    try {
      return JSON.parse(localStorage.getItem('citecheck.providers') ?? '{}')
    } catch {
      return {}
    }
  },
  save(sel: string, customs: CustomProvider[]) {
    try {
      localStorage.setItem(
        'citecheck.providers',
        JSON.stringify({ sel, customs })
      )
    } catch {
      /* localStorage unavailable — selection just won't persist */
    }
  },
}

/** Brand tile: colored rounded square + white glyph, macOS Settings style. */
function ProviderTile({ k, size }: { k: ProviderKey; size: number }) {
  const glyph = Math.round(size * 0.6)
  let bg = 'var(--tile-grey)'
  let icon: React.ReactNode = (
    <GearshapeFillIcon size={glyph} color="var(--on-brand)" />
  )
  if (k === 'dashscope') {
    bg = 'var(--brand-qwen)'
    icon = <QwenIcon size={glyph} color="var(--on-brand)" />
  } else if (k === 'deepseek') {
    bg = 'var(--brand-deepseek)'
    icon = <DeepSeekIcon size={glyph} color="var(--on-brand)" />
  } else if (k === 'openai') {
    bg = 'var(--text)'
    icon = <OpenAIIcon size={glyph} color="var(--bg)" />
  }
  return (
    <span className="provider-badge" style={{ background: bg }}>
      {icon}
    </span>
  )
}

/** Neutral tile for user-added endpoints: their picked glyph on grey. */
function CustomTile({ icon, size }: { icon: string; size: number }) {
  const glyph = Math.round(size * 0.6)
  return (
    <span className="provider-badge" style={{ background: 'var(--fill-strong)' }}>
      {BRAND_PATHS[icon] ? (
        <BrandIcon name={icon} size={glyph} color="var(--text)" />
      ) : (
        <GearshapeFillIcon size={glyph} color="var(--text)" />
      )}
    </span>
  )
}

/** Small brand glyph for a model name, used in usage rows. */
function ModelGlyph({ model }: { model?: string }) {
  const m = (model ?? '').toLowerCase()
  if (m.startsWith('qwen'))
    return <QwenIcon size={15} color="var(--brand-qwen)" />
  if (/^(gpt|o[134])/.test(m))
    return <OpenAIIcon size={15} color="var(--text)" />
  if (m.startsWith('deepseek'))
    return <DeepSeekIcon size={15} color="var(--brand-deepseek)" />
  return null
}

/** `compact` (onboarding): endpoint + key only, the per-task model grid
 * keeps its defaults and lives in Settings; `onSaved` fires on success */
export function ModelSection({
  compact = false,
  onSaved,
  leading,
  trailing,
}: {
  compact?: boolean
  onSaved?: () => void
  /** extra controls in the action row (onboarding: back / skip) */
  leading?: React.ReactNode
  trailing?: React.ReactNode
} = {}) {
  const [cfg, setCfg] = useState<ModelCfg | null>(null)
  const [key, setKey] = useState('')
  const [msg, setMsg] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [customs, setCustoms] = useState<CustomProvider[]>(
    () => providerStore.load().customs ?? []
  )
  const [sel, setSel] = useState(
    () => providerStore.load().sel ?? 'dashscope'
  )
  const [showAdd, setShowAdd] = useState(false)
  const [cname, setCname] = useState('')
  const [cbase, setCbase] = useState('')
  const [cicon, setCicon] = useState('ollama')

  useEffect(() => {
    if (window.citecheck.shotsMode) {
      setCfg(SHOT_CFG)
      return
    }
    apiFetch('/config')
      .then((r) => r.json())
      .then(setCfg)
      .catch(() => setMsg('设置服务不可用'))
  }, [])

  const persistProviders = (s: string, c: CustomProvider[]) =>
    providerStore.save(s, c)

  const applyPreset = (p: Preset) => {
    if (!cfg) return
    setCfg({ ...cfg, base_url: p.base, models: { ...p.models } })
    setSel(p.id)
    persistProviders(p.id, customs)
    setMsg(`已填入${p.name}的推荐配置，保存后生效`)
  }

  const applyCustom = (c: CustomProvider) => {
    if (!cfg) return
    setCfg({ ...cfg, base_url: c.base })
    setSel(c.name)
    persistProviders(c.name, customs)
    setMsg('已填入接口地址，模型名请按该端点修改，保存后生效')
  }

  const addCustom = () => {
    const name = cname.trim()
    const base = cbase.trim()
    if (!name || !base || customs.some((c) => c.name === name)) return
    const next = [...customs, { name, base, icon: cicon }]
    setCustoms(next)
    setCname('')
    setCbase('')
    setShowAdd(false)
    persistProviders(name, next)
    applyCustom({ name, base, icon: cicon })
  }

  const removeCustom = (i: number) => {
    const next = customs.filter((_, j) => j !== i)
    setCustoms(next)
    const nextSel = sel === customs[i].name ? 'dashscope' : sel
    setSel(nextSel)
    persistProviders(nextSel, next)
  }

  const save = async () => {
    if (!cfg) return
    setMsg('保存中')
    const r = await apiFetch('/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: cfg.base_url,
        dashscope_api_key: key || undefined,
        models: cfg.models,
      }),
    }).catch(() => null)
    if (r && r.ok) {
      const body = (await r.json()) as ModelCfg
      setCfg(body)
      setKey('')
      setMsg('已保存')
      onSaved?.()
    } else {
      const body = r ? await r.json().catch(() => null) : null
      setMsg(body?.detail ?? '保存失败，请检查后端是否运行')
    }
  }

  const pullModels = async () => {
    setMsg('拉取中')
    const r = await apiFetch('/models').catch(() => null)
    if (r && r.ok) {
      const body = (await r.json()) as { models?: string[] }
      setModels(body.models ?? [])
      setMsg(body.models?.length ? '模型列表已更新，点击输入框选择' : '没有拉取到模型列表')
    } else {
      const body = r ? await r.json().catch(() => null) : null
      setMsg(body?.detail ?? '拉取失败，请检查 API Key 和接口地址')
    }
  }

  if (!cfg)
    return <div className="secondary font-normal">{msg || '载入中'}</div>
  const actions = (
    <div className="settings-actions">
      {leading}
      <div className="flex-1" />
      {msg && <span className="t13 secondary">{msg}</span>}
      {trailing}
      <button className="pill-accent" onClick={save}>
        {compact ? '保存并继续' : '保存设置'}
      </button>
    </div>
  )
  return (
    <>
      {!compact && <h2 className="t20 settings-h">模型</h2>}
      <div className="group-label">选择服务商，或添加自己的 OpenAI 兼容端点</div>
      <div className="card">
        <div className="prov-grid">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              className={`prov-card${sel === p.id ? ' sel' : ''}`}
              onClick={() => applyPreset(p)}
            >
              <ProviderTile k={p.id} size={22} />
              <span>{p.name}</span>
            </button>
          ))}
          {customs.map((c) => (
            <button
              key={c.name}
              className={`prov-card${sel === c.name ? ' sel' : ''}`}
              onClick={() => applyCustom(c)}
            >
              <CustomTile icon={c.icon} size={22} />
              <span className="prov-card-name">{c.name}</span>
            </button>
          ))}
          <button
            className="prov-card prov-add"
            onClick={() => setShowAdd((v) => !v)}
          >
            <span
              className="provider-badge"
              style={{ background: 'var(--fill)' }}
            >
              <svg
                width={13}
                height={13}
                viewBox="0 0 24 24"
                fill="var(--text-secondary)"
                aria-hidden
              >
                <path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z" />
              </svg>
            </span>
            <span>添加端点</span>
          </button>
        </div>
        {customs.some((c) => c.name === sel) && (
          <button
            className="link-accent t13"
            style={{ marginTop: 8 }}
            onClick={() => removeCustom(customs.findIndex((c) => c.name === sel))}
          >
            移除这个端点
          </button>
        )}
        {showAdd && (
          <div className="prov-addform">
            <Field label="名称">
              <input
                className="field-input"
                value={cname}
                placeholder="例如：本地 Ollama"
                onChange={(e) => setCname(e.target.value)}
              />
            </Field>
            <Field label="Base URL">
              <input
                className="field-input"
                value={cbase}
                placeholder="http://127.0.0.1:11434/v1"
                onChange={(e) => setCbase(e.target.value)}
              />
            </Field>
            <Field label="图标">
              <div className="icon-grid">
                {Object.keys(BRAND_PATHS).map((n) => (
                  <button
                    key={n}
                    className={`icopt${cicon === n ? ' sel' : ''}`}
                    title={n}
                    onClick={() => setCicon(n)}
                  >
                    <BrandIcon name={n} size={16} color="var(--text)" />
                  </button>
                ))}
              </div>
            </Field>
            <div className="settings-actions" style={{ marginTop: 12 }}>
              <div className="flex-1" />
              <button className="pill" onClick={() => setShowAdd(false)}>
                取消
              </button>
              <button className="pill-accent" onClick={addCustom}>
                添加端点
              </button>
            </div>
          </div>
        )}
        <Field
          label="API Key"
          hint={cfg.has_api_key ? '已配置，输入新值可替换' : '尚未配置'}
        >
          <input
            className="field-input"
            type="password"
            value={key}
            placeholder="sk-…"
            onChange={(e) => setKey(e.target.value)}
          />
        </Field>
        <Field label="接口地址" hint="OpenAI 兼容的 /v1 地址">
          <input
            className="field-input"
            value={cfg.base_url}
            onChange={(e) => setCfg({ ...cfg, base_url: e.target.value })}
          />
        </Field>
      </div>
      {compact ? (
        actions
      ) : (
        <>
      <div className="group-label flex items-center">
        各任务使用的模型
        <div className="flex-1" />
        <button className="pill pill-s" onClick={pullModels}>
          拉取模型列表
        </button>
      </div>
      <div className="card model-fields">
        {TASK_FIELDS.map((t) => (
          <Field key={t.key} label={t.label}>
            <input
              className="field-input"
              list="model-list"
              value={cfg.models[t.key] ?? ''}
              onChange={(e) =>
                setCfg({
                  ...cfg,
                  models: { ...cfg.models, [t.key]: e.target.value },
                })
              }
            />
          </Field>
        ))}
        <datalist id="model-list">
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </div>
      {actions}
      <div className="group-label">
        费用记录与这些模型名对应，改名前的用量会保留在旧名字下
      </div>
        </>
      )}
    </>
  )
}

function UsageSection() {
  const [u, setU] = useState<Usage | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (window.citecheck.shotsMode) {
      setU(SHOT_USAGE)
      return
    }
    apiFetch('/usage')
      .then((r) => r.json())
      .then(setU)
      .catch(() => setErr('读取用量失败'))
  }, [])

  if (err) return <div className="secondary font-normal">{err}</div>
  if (!u) return <div className="secondary font-normal">载入中</div>
  const totalCalls = u.totals.reduce((s, r) => s + r.calls, 0)
  if (!totalCalls)
    return (
      <>
        <h2 className="t20 settings-h">用量与费用</h2>
        <div className="card secondary font-normal">
          还没有模型调用记录，跑一次体检后这里会出现统计。
        </div>
      </>
    )
  const totalPrompt = u.totals.reduce((s, r) => s + (r.prompt ?? 0), 0)
  const totalCompletion = u.totals.reduce((s, r) => s + (r.completion ?? 0), 0)
  const totalCached = u.totals.reduce((s, r) => s + (r.cached_calls ?? 0), 0)
  const totalCost = u.totals.every((r) => r.cost === null)
    ? null
    : u.totals.reduce((s, r) => s + (r.cost ?? 0), 0)

  // group by_doc rows by doc
  const docs = new Map<string, UsageRow[]>()
  for (const r of u.by_doc) {
    const k = r.doc ?? ''
    docs.set(k, [...(docs.get(k) ?? []), r])
  }
  const docCost = [...docs.entries()].map(([doc, rows]) => ({
    doc,
    rows,
    calls: rows.reduce((s, r) => s + r.calls, 0),
    cost: rows.reduce((s, r) => s + (r.cost ?? 0), 0),
  }))
  const maxDocCost = Math.max(...docCost.map((d) => d.cost), 0)

  // merge by_day rows (day × provider × model) into one entry per day
  const days = new Map<string, { tokens: number; cached: number }>()
  for (const r of u.by_day) {
    if (!r.day) continue
    const d = days.get(r.day) ?? { tokens: 0, cached: 0 }
    d.tokens += rowTokens(r)
    d.cached += r.cached_calls ?? 0
    days.set(r.day, d)
  }
  const dayList = [...days.entries()].sort().slice(-14)
  const maxDay = Math.max(...dayList.map(([, v]) => v.tokens), 1)

  return (
    <>
      <h2 className="t20 settings-h">用量与费用</h2>
      <div className="card usage-hero">
        <div className="t32 usage-hero-num">¥{yuan(totalCost)}</div>
        <div className="t13 secondary">累计估算花费</div>
        <div className="usage-stats">
          <div className="usage-stat">
            <div className="t20 usage-stat-num">{totalCalls}</div>
            <div className="t13 secondary">模型调用</div>
          </div>
          <div className="usage-stat">
            <div className="t20 usage-stat-num">{tokens(totalPrompt)}</div>
            <div className="t13 secondary">输入 token</div>
          </div>
          <div className="usage-stat">
            <div className="t20 usage-stat-num">{tokens(totalCompletion)}</div>
            <div className="t13 secondary">输出 token</div>
          </div>
          <div className="usage-stat">
            <div className="t20 usage-stat-num">{totalCached}</div>
            <div className="t13 secondary">缓存命中</div>
          </div>
        </div>
      </div>

      <div className="group-label">按论文</div>
      <div className="card usage-card">
        {docCost.map(({ doc, rows, calls, cost }) => (
          <div key={doc || '?'} className="usage-doc">
            <div className="usage-row">
              <span className="usage-name">{doc || '未关联文档'}</span>
              <Stats parts={[`${calls} 次`, `¥${yuan(cost)}`]} />
            </div>
            <div className="usage-bar">
              <i
                style={{
                  width: `${maxDocCost ? (cost / maxDocCost) * 100 : 0}%`,
                }}
              />
            </div>
            {rows.map((r, i) => (
              <div key={i} className="usage-row usage-sub">
                <span className="t13 usage-model">
                  <ModelGlyph model={r.model} />
                  {r.model}
                </span>
                <Stats
                  parts={[
                    `${r.calls} 次`,
                    `${tokens(rowTokens(r))} token`,
                    `¥${yuan(r.cost)}`,
                  ]}
                />
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="group-label">按供应商和模型</div>
      <div className="card usage-card">
        {u.by_provider.map((r, i) => (
          <div key={i} className="usage-row">
            <span className="usage-name usage-model">
              <ModelGlyph model={r.model} />
              {r.model}
              <span className="t13 secondary">{providerName(r.provider ?? "")}</span>
            </span>
            <Stats
              parts={[
                `${r.calls} 次`,
                `${tokens(rowTokens(r))} token`,
                `¥${yuan(r.cost)}`,
              ]}
            />
          </div>
        ))}
      </div>

      <div className="group-label">按天</div>
      <div className="card">
        <div className="usage-chart">
          {dayList.map(([day, v]) => (
            <div
              key={day}
              className="usage-col"
              title={`${day}：${tokens(v.tokens)} token${
                v.cached ? `，缓存命中 ${v.cached} 次` : ''
              }`}
            >
              <div
                className="usage-col-bar"
                style={{
                  height: `${Math.max(4, (v.tokens / maxDay) * 100)}%`,
                }}
              />
              <div className="t13 secondary usage-col-label">
                {day.slice(5).replace('-', '/')}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="group-label">缓存命中的调用不消耗 token，单独列出</div>
    </>
  )
}

// ------------------------------------------------------------- about

function AboutSection({ onCredits }: { onCredits: () => void }) {
  return (
    <>
      <div className="about-hero">
        <PageIcon size={56} />
        <h2 className="t20 settings-h" style={{ marginTop: 12 }}>
          {APP_NAME}
        </h2>
        <div className="secondary">版本 0.1.0</div>
        <p className="font-normal about-blurb">
          拖入一篇论文，检查参考文献是否真实、引用是否支持论断，问题以批注和修订写回 Word。判断由通义千问完成，也可以接入你自己维护的 OpenAI 兼容端点。
        </p>
        <button
          className="pill flex items-center gap-2"
          style={{ marginTop: 16 }}
          onClick={() => window.citecheck.openExternal(GITHUB_URL)}
        >
          <GitHubMarkIcon size={15} />
          <span className="font-normal">在 GitHub 上查看源代码</span>
        </button>
      </div>
      {CREDITS.map(({ group, items }) => (
        <section key={group}>
          <div className="group-label">{group}</div>
          <div className="card about-card">
            {items.map(([name, role, url]) => (
              <button
                key={name}
                className="about-row"
                onClick={() => window.citecheck.openExternal(url)}
              >
                <span className="font-normal">{name}</span>
                <span className="t13 secondary">{role}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
      <div className="about-thanks">
        <div className="t13 secondary">
          感谢这些项目和数据服务，没有它们就没有这个应用。
        </div>
        <button className="pill pill-s" onClick={onCredits}>
          致谢
        </button>
      </div>
    </>
  )
}
