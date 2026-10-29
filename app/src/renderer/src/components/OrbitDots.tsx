import { useEffect, useRef } from 'react'
import {
  TURNS_PER_SECOND,
  defaultTilt,
  orbitPose,
  stillPose,
  wobbleTilt,
  type DotPose,
} from '../lib/orbit'

const DOTS = 3
const COLLAPSE_MS = 240

/** 三点轨道：时长不定、要等模型返回的场合用它，短等待继续用转圈。
 *  rAF 只写 transform、opacity、z-index；离屏或页面隐藏时停帧。
 *  `collapsed` 变为 true 后半径在 240ms 内收拢到 0，结束时调用 onCollapsed。
 *  减少动态效果：三点排成一行静止，只做依次明暗。 */
export default function OrbitDots({
  size = 14,
  color = 'var(--tile-pink)',
  collapsed = false,
  onCollapsed,
}: {
  size?: number
  color?: string
  collapsed?: boolean
  onCollapsed?: () => void
}) {
  const root = useRef<HTMLSpanElement>(null)
  const dots = useRef<(HTMLSpanElement | null)[]>([])
  const collapseAt = useRef<number | null>(null)
  const onDone = useRef(onCollapsed)
  onDone.current = onCollapsed

  useEffect(() => {
    if (collapsed && collapseAt.current == null) {
      collapseAt.current = performance.now()
    }
    if (!collapsed) collapseAt.current = null
  }, [collapsed])

  useEffect(() => {
    const el = root.current
    if (!el) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const radius = size * 0.3
    const baseTilt = defaultTilt(size)
    let raf = 0
    let visible = true
    let notified = false
    let start = performance.now()

    const paint = (p: DotPose, d: HTMLSpanElement) => {
      d.style.transform = `translate(${p.x}px, ${p.y}px) scale(${p.scale})`
      d.style.opacity = String(p.opacity)
      d.style.zIndex = String(p.z)
    }
    const frame = (now: number) => {
      raf = 0
      const t = (now - start) / 1000
      const phase = t * (reduce ? 0.6 : TURNS_PER_SECOND)
      let collapse = 0
      if (collapseAt.current != null) {
        const k = Math.min(1, (now - collapseAt.current) / COLLAPSE_MS)
        collapse = 1 - Math.pow(1 - k, 3)
        if (k >= 1 && !notified) {
          notified = true
          onDone.current?.()
        }
      }
      for (let i = 0; i < DOTS; i++) {
        const d = dots.current[i]
        if (!d) continue
        paint(
          reduce
            ? stillPose(phase, i, DOTS, size * 0.3)
            : orbitPose(phase, i, DOTS, {
                radius,
                tilt: wobbleTilt(baseTilt, size, t),
                collapse,
              }),
          d
        )
      }
      if (visible && !document.hidden) raf = requestAnimationFrame(frame)
    }
    const kick = () => {
      if (!raf && visible && !document.hidden) {
        // 离屏期间时间照走，回来时从当前相位继续，不跳变
        raf = requestAnimationFrame(frame)
      }
    }
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting
      kick()
    })
    io.observe(el)
    document.addEventListener('visibilitychange', kick)
    start = performance.now()
    kick()
    return () => {
      io.disconnect()
      document.removeEventListener('visibilitychange', kick)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [size])

  const d = Math.max(3, Math.round(size * 0.3))
  return (
    <span
      ref={root}
      role="img"
      aria-label="正在处理"
      style={{
        position: 'relative',
        display: 'inline-block',
        width: size,
        height: size,
        flex: 'none',
      }}
    >
      {Array.from({ length: DOTS }, (_, i) => (
        <span
          key={i}
          ref={(n) => {
            dots.current[i] = n
          }}
          style={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: d,
            height: d,
            marginLeft: -d / 2,
            marginTop: -d / 2,
            borderRadius: '50%',
            background: color,
            willChange: 'transform, opacity',
          }}
        />
      ))}
    </span>
  )
}
