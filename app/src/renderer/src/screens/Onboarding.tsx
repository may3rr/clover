import { useEffect, useRef, useState } from 'react'
import RingField, { type FieldMode } from '../components/RingField'
import { ModelSection, ProfileEditor, pickAvatarImage } from './Settings'
import {
  BooksFillIcon,
  DesktopFillIcon,
  GitHubMarkIcon,
  LayerTile,
  LockFillIcon,
  PaperplaneFillIcon,
} from '../components/Icons'
import { putPrefs, type Prefs } from '../lib/prefs'
import { GITHUB_URL } from '../lib/credits'
import { APP_NAME, APP_TAGLINE } from '../lib/brand'
import ShuffleTitle from '../components/ShuffleTitle'

/** First run: a short intro, then model endpoint → name & avatar →
 * privacy consent. The app opens only after the privacy note is ticked. */

export type OnboardStep = 0 | 1 | 2 | 3

export default function Onboarding({
  prefs,
  onPrefs,
  onDone,
  initialStep = 0,
}: {
  prefs: Prefs
  onPrefs: (p: Prefs) => void
  onDone: () => void
  initialStep?: OnboardStep
}) {
  const [step, setStep] = useState<OnboardStep>(initialStep)
  const [agreed, setAgreed] = useState(false)
  const [leaving, setLeaving] = useState(false)
  // intro beats: dots scatter → rings form → words arrive
  const [beat, setBeat] = useState(
    initialStep === 0 && !window.citecheck.shotsMode ? 0 : 2
  )
  const avatarRef = useRef<HTMLDivElement>(null)
  const lockRef = useRef<HTMLDivElement>(null)

  // beat 0 → 1: scattered dots gather into rings; the title starts
  // flickering once they have settled; beat 2 arrives when it lands
  const [shuffle, setShuffle] = useState(beat >= 2)
  // keyed on step only — re-running on beat would cancel the title timer
  useEffect(() => {
    if (step !== 0 || shuffle) return
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    const a = setTimeout(() => setBeat((b) => Math.max(b, 1)), reduced ? 0 : 700)
    const b = setTimeout(() => setShuffle(true), reduced ? 0 : 1700)
    return () => {
      clearTimeout(a)
      clearTimeout(b)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step])

  const update = (patch: Partial<Prefs>) => onPrefs({ ...prefs, ...patch })
  const pickImage = async () => {
    const image = await pickAvatarImage()
    if (image) update({ avatar: { kind: 'image', color: prefs.avatar.color, image } })
  }
  const go = (s: OnboardStep) => {
    if (step === 2) putPrefs(prefs).catch(() => {})
    setStep(s)
  }
  const finish = async () => {
    const next = { ...prefs, onboarded: true }
    onPrefs(next)
    putPrefs(next).catch(() => {})
    setLeaving(true)
    setTimeout(onDone, 640)
  }

  const mode: FieldMode = leaving
    ? { kind: 'burst' }
    : step === 0
      ? beat === 0
        ? { kind: 'scatter' }
        : { kind: 'rings' }
      : step === 2
        ? {
            kind: 'orbit',
            anchor: () =>
              avatarRef.current
                ?.querySelector('.avatar-btn')
                ?.getBoundingClientRect() ?? null,
            radius: 50,
            tight: true,
          }
        : step === 3
          ? {
              kind: 'orbit',
              anchor: () => lockRef.current?.getBoundingClientRect() ?? null,
              radius: agreed ? 30 : 40,
              tight: true,
            }
          : { kind: 'halo' }

  return (
    <div
      className="onboard relative h-full overflow-hidden"
      style={{ background: 'var(--bg)' }}
    >
      <RingField mode={mode} />
      <div
        className="drag-strip"
        style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 52 }}
      />

      <div
        key={step}
        className={`onboard-stage${leaving ? ' leaving' : ''}`}
      >
        {step === 0 && (
          <div className={`onboard-intro${beat >= 2 ? ' on' : ''}`}>
            <ShuffleTitle
              className="onboard-shuffle"
              text={APP_TAGLINE}
              play={shuffle}
              onSettled={() => setTimeout(() => setBeat(2), 420)}
            />
            <div className="t26 onboard-rise" style={{ fontWeight: 600, marginTop: 24 }}>
              {APP_NAME}
            </div>
            <div className="secondary onboard-rise" style={{ marginTop: 8 }}>
              投稿之前，最后检查一遍引用。
            </div>
            <button
              className="pill-accent onboard-rise"
              style={{ marginTop: 32 }}
              onClick={() => go(1)}
            >
              开始设置
            </button>
          </div>
        )}

        {step === 1 && (
          <div className="onboard-panel" style={{ width: 560 }}>
            <h1 className="t26 onboard-h">连接模型服务</h1>
            <p className="secondary onboard-sub">
              {APP_NAME} 用大模型判断引用是否支持论断。默认使用阿里云百炼的通义千问，也可以填入你自己维护的 OpenAI 兼容端点。
            </p>
            <div className="onboard-model">
              <ModelSection
                compact
                onSaved={() => go(2)}
                leading={
                  <button className="pill" onClick={() => go(0)}>
                    返回
                  </button>
                }
                trailing={
                  <button className="link-quiet t13" onClick={() => go(2)}>
                    稍后配置
                  </button>
                }
              />
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="onboard-panel" style={{ width: 440 }}>
            <h1 className="t26 onboard-h" style={{ textAlign: 'center' }}>
              怎么称呼你
            </h1>
            <p className="secondary onboard-sub" style={{ textAlign: 'center' }}>
              名字会出现在窗口左下角，也是导出到 Word 的批注署名。
            </p>
            <div ref={avatarRef} className="onboard-avatar-anchor">
              <ProfileEditor prefs={prefs} update={update} pickImage={pickImage} />
            </div>
            <div className="onboard-nav">
              <button className="pill" onClick={() => go(1)}>
                返回
              </button>
              <button className="pill-accent" onClick={() => go(3)}>
                继续
              </button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="onboard-panel" style={{ width: 520 }}>
            <div ref={lockRef} className="onboard-lock">
              <LayerTile size={40} color="var(--tile-indigo)" icon={<LockFillIcon size={22} />} />
            </div>
            <h1 className="t26 onboard-h" style={{ textAlign: 'center' }}>
              你的论文只属于你
            </h1>
            <div className="onboard-privacy">
              <PrivacyRow
                icon={<LockFillIcon size={13} />}
                color="var(--tile-indigo)"
                title="不收集任何数据"
                body="没有账号，没有使用统计，没有遥测。"
              />
              <PrivacyRow
                icon={<DesktopFillIcon size={13} />}
                color="var(--tile-blue)"
                title="一切留在这台 Mac 上"
                body="论文在本机解析，检查记录、设置和缓存都存在本地，没有任何同步服务。"
              />
              <PrivacyRow
                icon={<PaperplaneFillIcon size={13} />}
                color="var(--tile-teal)"
                title="只发给你配置的模型服务"
                body="判断引用时，论断和相关片段会发送到你选择的模型服务商。期刊对标还会发送论文的标题、摘要、章节标题和图表题注。不会上传整篇稿件，也不经过我们的服务器。"
              />
              <PrivacyRow
                icon={<BooksFillIcon size={13} />}
                color="var(--tile-purple)"
                title="核验文献和对标期刊时访问公开数据库"
                body="参考文献的标题、作者和 DOI 会发送到 Crossref、OpenAlex、Semantic Scholar 和 arXiv 检索。期刊对标会从 ACL Anthology 下载已发表的公开论文，不发送你的稿件。"
              />
              <PrivacyRow
                icon={<GitHubMarkIcon size={13} />}
                color="var(--tile-grey)"
                title="代码开源"
                body="以上每一条都可以在源代码里核对。"
                action={
                  <button
                    className="link-accent t13"
                    onClick={() => window.citecheck.openExternal(GITHUB_URL)}
                  >
                    在 GitHub 上查看
                  </button>
                }
              />
            </div>
            <label className="onboard-consent">
              <input
                type="checkbox"
                checked={agreed}
                onChange={(e) => setAgreed(e.target.checked)}
              />
              <span>我已了解以上说明，同意按这种方式处理我的论文</span>
            </label>
            <div className="onboard-nav">
              <button className="pill" onClick={() => go(2)}>
                返回
              </button>
              <button className="pill-accent" disabled={!agreed} onClick={finish}>
                开始使用
              </button>
            </div>
          </div>
        )}
      </div>

      {step > 0 && !leaving && (
        <div className="onboard-dots" aria-label={`第 ${step} 步，共 3 步`}>
          {[1, 2, 3].map((i) => (
            <span key={i} className={i === step ? 'on' : undefined} />
          ))}
        </div>
      )}
    </div>
  )
}

function PrivacyRow({
  icon,
  color,
  title,
  body,
  action,
}: {
  icon: React.ReactNode
  color: string
  title: string
  body: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex" style={{ gap: 12 }}>
      <LayerTile size={22} color={color} icon={icon} />
      <div className="min-w-0">
        <div className="font-semibold">{title}</div>
        <div className="t13 secondary" style={{ marginTop: 2 }}>
          {body}
        </div>
        {action && <div style={{ marginTop: 4 }}>{action}</div>}
      </div>
    </div>
  )
}
