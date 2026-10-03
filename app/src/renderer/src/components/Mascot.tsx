import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from 'react'
import {
  BOTTOM,
  CX,
  HEAD_D,
  EYE_D,
  HEAD_W,
  VIEWBOX,
  MascotEngine,
  attachMascot,
  getEyeMetrics,
  type MascotAction,
  type MascotState,
  type MascotStance,
} from '../lib/mascot'

export type { MascotAction, MascotState, MascotStance }

export interface MascotHandle {
  /** play a one-shot action on top of the current state */
  play: (action: MascotAction) => void
}

interface Props {
  /** body color, always a CSS variable such as 'var(--tile-indigo)' */
  color: string
  /** width of the head in px; the box is size x size, motion may overflow it */
  size?: number
  state?: MascotState
  stance?: MascotStance
  /** plays `cue.action` whenever `cue.key` changes (the first value is ignored) */
  cue?: { action: MascotAction; key: string | number } | null
  /** accessible name; omit for a decorative mascot */
  label?: string
  style?: React.CSSProperties
  className?: string
}

let uid = 0

/**
 * One agent as a small blob with two eyes. Animated by the shared engine in
 * lib/mascot.ts; with prefers-reduced-motion it renders a static pose.
 */
const Mascot = forwardRef<MascotHandle, Props>(function Mascot(
  {
    color,
    size = 28,
    state = 'idle',
    stance = 'none',
    cue,
    label,
    style,
    className,
  },
  ref
) {
  const clipId = useMemo(() => `mascot-clip-${uid++}`, [])
  const eye = useMemo(() => getEyeMetrics(), [])
  const shadowRef = useRef<SVGEllipseElement>(null)
  const bodyRef = useRef<SVGGElement>(null)
  const eyesRef = useRef<SVGGElement>(null)
  const eyeLRef = useRef<SVGGElement>(null)
  const eyeRRef = useRef<SVGGElement>(null)
  const engine = useRef<MascotEngine | null>(null)
  const first = useRef({ state, stance, cue: cue?.key })

  useEffect(() => {
    const els = {
      shadow: shadowRef.current,
      body: bodyRef.current,
      eyes: eyesRef.current,
      eyeL: eyeLRef.current,
      eyeR: eyeRRef.current,
    }
    if (!els.shadow || !els.body || !els.eyes || !els.eyeL || !els.eyeR) return
    // a random phase keeps several mascots from bobbing in lockstep
    const m = new MascotEngine(
      els as ConstructorParameters<typeof MascotEngine>[0],
      eye,
      Math.random()
    )
    m.setState(first.current.state, true)
    m.setStance(first.current.stance)
    engine.current = m
    const detach = attachMascot(m)
    return () => {
      detach()
      engine.current = null
    }
  }, [eye])

  useEffect(() => {
    engine.current?.setState(state)
  }, [state])
  useEffect(() => {
    engine.current?.setStance(stance)
  }, [stance])
  useEffect(() => {
    if (!cue || cue.key === first.current.cue) return
    engine.current?.play(cue.action)
  }, [cue?.action, cue?.key]) // eslint-disable-line react-hooks/exhaustive-deps

  useImperativeHandle(ref, () => ({ play: (a) => engine.current?.play(a) }), [])

  const k = size / HEAD_W
  return (
    <span
      className={className}
      style={{
        position: 'relative',
        display: 'inline-block',
        width: size,
        height: size,
        flex: 'none',
        ...style,
      }}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <svg
        viewBox={`${VIEWBOX.x} ${VIEWBOX.y} ${VIEWBOX.w} ${VIEWBOX.h}`}
        width={VIEWBOX.w * k}
        height={VIEWBOX.h * k}
        style={{
          position: 'absolute',
          left: VIEWBOX.x * k,
          top: VIEWBOX.y * k,
          overflow: 'visible',
          pointerEvents: 'none',
        }}
      >
        <defs>
          <clipPath id={clipId}>
            <path d={HEAD_D} />
          </clipPath>
        </defs>
        <ellipse
          ref={shadowRef}
          cx={CX}
          cy={BOTTOM + 24}
          rx={80}
          ry={11}
          style={{ fill: 'var(--text)', fillOpacity: 0.1 }}
        />
        <g ref={bodyRef}>
          <path d={HEAD_D} style={{ fill: color }} />
          <g clipPath={`url(#${clipId})`}>
            <g ref={eyesRef}>
              {[eyeLRef, eyeRRef].map((r, i) => (
                <g key={i} ref={r}>
                  <path
                    d={EYE_D}
                    transform={`translate(${-eye.center[0]} ${-eye.center[1]})`}
                    style={{ fill: 'var(--on-tile)' }}
                  />
                </g>
              ))}
            </g>
          </g>
        </g>
      </svg>
    </span>
  )
})

export default Mascot
