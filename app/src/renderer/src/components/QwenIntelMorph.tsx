import { useEffect, useRef } from 'react'
import { interpolate } from 'flubber'
import { LOGO_PATHS } from '../lib/logoPaths'
import {
  PIECE_MAP,
  bbox,
  holeK,
  intelTransform,
  mixHex,
  parseHex,
  pieceT,
  scalePath,
  spinTransform,
  stageAt,
} from '../lib/logoMorph'

/** 千问 logo 转两圈、变成英特尔 logo、字母弹跳、再变回千问，循环播放。
 *  表示「千问模型正在这台英特尔电脑上运行」：运行页标题旁的加载动画，
 *  以及窗口不在前台时的进度浮窗。
 *  颜色取 tokens.css 的 --brand-qwen / --brand-intel / --brand-intel-dot；
 *  减少动态效果时停在千问 logo。 */
export default function QwenIntelMorph({ width = 56 }: { width?: number }) {
  const gRef = useRef<SVGGElement>(null)
  const pathRefs = useRef<(SVGPathElement | null)[]>([])

  useEffect(() => {
    const css = getComputedStyle(document.documentElement)
    const color = (name: string) => parseHex(css.getPropertyValue(name))
    const qwen = color('--brand-qwen')
    const tones = { dot: color('--brand-intel-dot'), letter: color('--brand-intel') }
    const pieces = PIECE_MAP.map((p) => {
      const from = LOGO_PATHS.qwen[p.q]
      const to = LOGO_PATHS.intel[p.i]
      const hole = p.hole != null ? LOGO_PATHS.intel[p.hole] : null
      const hb = hole ? bbox(hole) : null
      return {
        ...p,
        from,
        to,
        b: bbox(to),
        interp: interpolate(from, to, { maxSegmentLength: 1 }),
        hole,
        holeC: hb ? ([(hb.x0 + hb.x1) / 2, (hb.y0 + hb.y1) / 2] as const) : null,
      }
    })
    const n = pieces.length
    const els = pathRefs.current
    const paint = (stage: ReturnType<typeof stageAt>['stage'], local: number) => {
      gRef.current?.setAttribute('transform', stage === 'spin' ? spinTransform(local) : '')
      pieces.forEach((p, idx) => {
        const el = els[idx]
        if (!el) return
        const t = pieceT(stage, local, idx, n)
        let d = t <= 0 ? p.from : t >= 1 ? p.to : p.interp(t)
        if (p.hole && p.holeC) {
          const k = holeK(t)
          if (k > 0.001) d += ' ' + (k >= 1 ? p.hole : scalePath(p.hole, k, p.holeC[0], p.holeC[1]))
        }
        el.setAttribute('d', d)
        el.setAttribute('fill', mixHex(qwen, tones[p.tone], t))
        el.setAttribute('transform', stage === 'intel' ? intelTransform(p.role, p.b, idx, local) : '')
      })
    }

    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      paint('hold3', 0)
      return
    }
    let raf = 0
    const t0 = performance.now()
    const frame = (now: number) => {
      const { stage, local } = stageAt(now - t0)
      paint(stage, local)
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <svg
      viewBox="0 0 140 100"
      width={width}
      height={(width * 100) / 140}
      style={{ overflow: 'visible', flex: 'none' }}
      aria-hidden="true"
    >
      <g ref={gRef}>
        {PIECE_MAP.map((p, i) => (
          <path
            key={i}
            ref={(el) => {
              pathRefs.current[i] = el
            }}
            fillRule={p.hole != null ? 'evenodd' : undefined}
          />
        ))}
      </g>
    </svg>
  )
}
