import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../lib/api'
import {
  commentAuthor,
  commentInitials,
  putPrefs,
  type Prefs,
} from '../lib/prefs'
import Avatar from '../components/Avatar'
import {
  ChevronLeftIcon,
  SealCheckFillIcon,
  PersonFillIcon,
  QuoteBubbleFillIcon,
  GearshapeFillIcon,
  ChartBarFillIcon,
  LayerTile,
} from '../components/Icons'

/** Left-nav pane + grouped fields, in the style of macOS Settings. */

type Section = 'account' | 'comments' | 'model' | 'usage'
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
  initialSection = 'account',
}: {
  prefs: Prefs
  onPrefs: (p: Prefs) => void
  onBack: () => void
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
    const raw = await window.citecheck.pickAvatar().catch(() => null)
    if (!raw) return
    const small = await downscale(raw)
    update({ avatar: { kind: 'image', color: prefs.avatar.color, image: small } })
  }

  return (
    <div className="relative h-full overflow-hidden">
      <aside className="settings-nav">
        <nav className="flex flex-col gap-1" style={{ padding: '0 8px' }}>
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
      </aside>
      <div className="flex flex-col h-full" style={{ marginLeft: 200 }}>
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
          <div className="font-semibold">设置</div>
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

function AccountSection({
  prefs,
  update,
  pickImage,
}: {
  prefs: Prefs
  update: (p: Partial<Prefs>) => void
  pickImage: () => void
}) {
  return (
    <>
      <h2 className="t20 settings-h">账户</h2>
      <div className="group-label">头像和名字会显示在侧栏左下角</div>
      <div className="card account-head">
        <Avatar prefs={prefs} size={56} />
        <div className="flex flex-col gap-2">
          <button className="pill-accent" onClick={pickImage}>
            选择图片
          </button>
          {prefs.avatar.kind === 'image' && (
            <button
              className="pill"
              onClick={() =>
                update({
                  avatar: { ...prefs.avatar, kind: 'color', image: null },
                })
              }
            >
              移除图片
            </button>
          )}
        </div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
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
        <Field label="你的名字">
          <input
            className="field-input"
            value={prefs.name}
            placeholder="例如 小明"
            onChange={(e) => update({ name: e.target.value })}
          />
        </Field>
      </div>
    </>
  )
}

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
            placeholder={prefs.name || '引用体检'}
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
    {
      day: '2026-10-06',
      provider: 'dashscope',
      model: 'qwen3.8-flash',
      calls: 80,
      cached_calls: 0,
      prompt: 319000,
      completion: 40000,
      cost: 0.3632,
    },
    {
      day: '2026-10-06',
      provider: 'dashscope',
      model: 'qwen3.7-flash',
      calls: 47,
      cached_calls: 6,
      prompt: 33000,
      completion: 5200,
      cost: 0.0108,
    },
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

function ModelSection() {
  const [cfg, setCfg] = useState<ModelCfg | null>(null)
  const [key, setKey] = useState('')
  const [msg, setMsg] = useState('')
  const [models, setModels] = useState<string[]>([])

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
      setMsg(body.models?.length ? '' : '没有拉取到模型列表')
    } else {
      const body = r ? await r.json().catch(() => null) : null
      setMsg(body?.detail ?? '拉取失败，请检查 API Key 和接口地址')
    }
  }

  if (!cfg)
    return <div className="secondary font-normal">{msg || '载入中'}</div>
  return (
    <>
      <h2 className="t20 settings-h">模型</h2>
      <div className="group-label">API 接口</div>
      <div className="card">
        <div className="provider-card">
          <span className="provider-badge">
            <SealCheckFillIcon size={16} color="var(--ok)" />
          </span>
          <div className="min-w-0">
            <div className="provider-name font-normal">阿里云百炼</div>
            <div className="t13 secondary">DashScope OpenAI 兼容接口</div>
          </div>
        </div>
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
      <div className="group-label">各任务使用的模型</div>
      <div className="card">
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
      <div className="settings-actions">
        <button className="pill-accent" onClick={save}>
          保存设置
        </button>
        <button className="pill" onClick={pullModels}>
          拉取模型列表
        </button>
        {msg && <span className="t13 secondary">{msg}</span>}
      </div>
      <div className="group-label">
        费用记录与这些模型名对应，改名前的用量会保留在旧名字下
      </div>
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
  const totalCost = u.totals.every((r) => r.cost === null)
    ? null
    : u.totals.reduce((s, r) => s + (r.cost ?? 0), 0)

  // group by_doc rows by doc
  const docs = new Map<string, UsageRow[]>()
  for (const r of u.by_doc) {
    const k = r.doc ?? ''
    docs.set(k, [...(docs.get(k) ?? []), r])
  }

  return (
    <>
      <h2 className="t20 settings-h">用量与费用</h2>
      <div className="card usage-total">
        <div className="t20 usage-total-num">¥{yuan(totalCost)}</div>
        <div className="t13 secondary" style={{ marginTop: 4 }}>
          累计估算花费 · {totalCalls} 次调用 · 输入 {tokens(totalPrompt)} · 输出{' '}
          {tokens(totalCompletion)}
        </div>
      </div>

      <div className="group-label">按论文</div>
      <div className="card usage-card">
        {[...docs.entries()].map(([doc, rows]) => {
          const calls = rows.reduce((s, r) => s + r.calls, 0)
          const cost = rows.reduce((s, r) => s + (r.cost ?? 0), 0)
          return (
            <div key={doc || '?'} className="usage-doc">
              <div className="usage-row">
                <span className="usage-name">{doc || '未关联文档'}</span>
                <span className="t13 secondary">
                  {calls} 次 · ¥{yuan(cost)}
                </span>
              </div>
              {rows.map((r, i) => (
                <div key={i} className="usage-row usage-sub">
                  <span className="t13">{r.model}</span>
                  <span className="t13 secondary">
                    {r.calls} 次 · {tokens(rowTokens(r))} tok · ¥
                    {yuan(r.cost)}
                  </span>
                </div>
              ))}
            </div>
          )
        })}
      </div>

      <div className="group-label">按供应商和模型</div>
      <div className="card usage-card">
        {u.by_provider.map((r, i) => (
          <div key={i} className="usage-row">
            <span className="usage-name">
              {r.provider} · {r.model}
            </span>
            <span className="t13 secondary">
              {r.calls} 次 · {tokens(rowTokens(r))} tok · ¥{yuan(r.cost)}
            </span>
          </div>
        ))}
      </div>

      <div className="group-label">按天</div>
      <div className="card usage-card">
        {u.by_day.map((r, i) => (
          <div key={i} className="usage-row">
            <span className="usage-name">
              {r.day} · {r.model}
            </span>
            <span className="t13 secondary">
              {r.calls} 次 · {tokens(rowTokens(r))} tok
              {r.cached_calls ? ` · 缓存 ${r.cached_calls}` : ''}
            </span>
          </div>
        ))}
      </div>
      <div className="group-label">缓存命中的调用不消耗 token，单独列出</div>
    </>
  )
}
