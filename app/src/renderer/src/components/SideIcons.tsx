import { useId } from 'react'

// Sidebar glyphs: filled, transparent background, one 20x20 grid with the
// live area inside 2..18 so every icon sits optically centred in the 20px
// box the old tiles used (text never shifts). Cut-outs are real holes made
// with an SVG mask, so nothing depends on the pane colour behind the icon.
// Colour: neutral glyphs follow --text-secondary (--text on the selected
// row); layer glyphs carry their layer hue via the `hue` prop.

export type SideIconName =
  | 'all'
  | 'authenticity'
  | 'support'
  | 'distribution'
  | 'norms'
  | 'plus'
  | 'doc'
  | 'account'
  | 'comments'
  | 'model'
  | 'usage'
  | 'about'

/** scalloped badge for the authenticity seal */
function rosette(cx: number, cy: number, rOut: number, rIn: number, lobes: number) {
  const pts: string[] = []
  for (let i = 0; i < lobes * 2; i++) {
    const a = (Math.PI * i) / lobes - Math.PI / 2
    const r = i % 2 === 0 ? rOut : rIn
    pts.push(
      `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`
    )
  }
  return `M${pts.join('L')}Z`
}
const SEAL = rosette(10, 10, 8.6, 7.5, 10)

const CUT = { fill: 'black' } as const
const CUT_STROKE = {
  fill: 'none',
  stroke: 'black',
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

// each glyph: solid shape + optional cut-out shapes (drawn in black)
const GLYPHS: Record<
  SideIconName,
  { shape: React.ReactNode; cut?: React.ReactNode }
> = {
  // inbox tray
  all: {
    shape: (
      <path d="M5.3 3h9.4c.7 0 1.3.4 1.6 1l2.4 5v6.3A2.7 2.7 0 0 1 16 18H4a2.7 2.7 0 0 1-2.7-2.7V9l2.4-5c.3-.6.9-1 1.6-1z" />
    ),
    cut: (
      <path
        {...CUT}
        d="M6.1 5 4.4 9h3.1a2.5 2.5 0 0 0 5 0h3.1L13.9 5z"
      />
    ),
  },
  // scalloped seal with a check
  authenticity: {
    shape: <path d={SEAL} stroke="currentColor" strokeWidth={1} strokeLinejoin="round" />,
    cut: (
      <path
        {...CUT_STROKE}
        strokeWidth={1.8}
        d="M6.6 10.2l2.5 2.5 4.4-4.9"
      />
    ),
  },
  // speech bubble with two quote marks
  support: {
    shape: (
      <path d="M10 2.5c-4.4 0-8 2.9-8 6.6 0 2.1 1.1 3.9 2.9 5.1-.2 1.1-.8 2-1.5 2.7-.3.3-.1.8.3.8 1.9-.1 3.4-.8 4.5-1.8.6.1 1.2.2 1.8.2 4.4 0 8-2.9 8-6.6S14.4 2.5 10 2.5z" />
    ),
    cut: (
      <>
        <circle {...CUT} cx="7.2" cy="8.3" r="1.35" />
        <path {...CUT_STROKE} strokeWidth={1.7} d="M7.3 9.2 6.5 11.6" />
        <circle {...CUT} cx="12.4" cy="8.3" r="1.35" />
        <path {...CUT_STROKE} strokeWidth={1.7} d="M12.5 9.2 11.7 11.6" />
      </>
    ),
  },
  // three bars
  distribution: {
    shape: (
      <>
        <rect x="2.5" y="10" width="3.8" height="7.5" rx="1.2" />
        <rect x="8.1" y="2.5" width="3.8" height="15" rx="1.2" />
        <rect x="13.7" y="6.5" width="3.8" height="11" rx="1.2" />
      </>
    ),
  },
  // capital A
  norms: {
    shape: (
      <path
        fillRule="evenodd"
        d="M9.3 2.8h1.4l5.3 14.2h-2.4l-1.2-3.4H7.6L6.4 17H4zm-.9 8.8h3.2L10 6.9z"
      />
    ),
  },
  plus: {
    shape: (
      <>
        <rect x="8.9" y="3.5" width="2.2" height="13" rx="1.1" />
        <rect x="3.5" y="8.9" width="13" height="2.2" rx="1.1" />
      </>
    ),
  },
  // page with folded corner and two text lines
  doc: {
    shape: (
      <path d="M5.6 2h5.5l4.9 4.9v8.6a2.5 2.5 0 0 1-2.5 2.5H5.6a2.5 2.5 0 0 1-2.5-2.5v-11A2.5 2.5 0 0 1 5.6 2z" />
    ),
    cut: (
      <>
        <path
          {...CUT_STROKE}
          strokeWidth={1.3}
          d="M11.1 2.2v3.4c0 .8.5 1.3 1.3 1.3h3.5"
        />
        <rect {...CUT} x="6" y="10.1" width="8" height="1.5" rx=".75" />
        <rect {...CUT} x="6" y="13.2" width="5.2" height="1.5" rx=".75" />
      </>
    ),
  },
  account: {
    shape: (
      <>
        <circle cx="10" cy="6.4" r="3.6" />
        <path d="M10 11.6c-3.8 0-6.5 2.3-6.5 5 0 .8.6 1.4 1.4 1.4h10.2c.8 0 1.4-.6 1.4-1.4 0-2.7-2.7-5-6.5-5z" />
      </>
    ),
  },
  // bubble with text lines (comment signature)
  comments: {
    shape: (
      <path d="M10 2.5c-4.4 0-8 2.9-8 6.6 0 2.1 1.1 3.9 2.9 5.1-.2 1.1-.8 2-1.5 2.7-.3.3-.1.8.3.8 1.9-.1 3.4-.8 4.5-1.8.6.1 1.2.2 1.8.2 4.4 0 8-2.9 8-6.6S14.4 2.5 10 2.5z" />
    ),
    cut: (
      <>
        <rect {...CUT} x="5.8" y="7.1" width="8.4" height="1.5" rx=".75" />
        <rect {...CUT} x="5.8" y="10" width="5.4" height="1.5" rx=".75" />
      </>
    ),
  },
  // chip
  model: {
    shape: (
      <>
        <rect x="4.5" y="4.5" width="11" height="11" rx="2.6" />
        <rect x="7.4" y="2" width="1.5" height="2.4" rx=".75" />
        <rect x="11.1" y="2" width="1.5" height="2.4" rx=".75" />
        <rect x="7.4" y="15.6" width="1.5" height="2.4" rx=".75" />
        <rect x="11.1" y="15.6" width="1.5" height="2.4" rx=".75" />
        <rect x="2" y="7.4" width="2.4" height="1.5" rx=".75" />
        <rect x="2" y="11.1" width="2.4" height="1.5" rx=".75" />
        <rect x="15.6" y="7.4" width="2.4" height="1.5" rx=".75" />
        <rect x="15.6" y="11.1" width="2.4" height="1.5" rx=".75" />
      </>
    ),
    cut: <rect {...CUT} x="7.7" y="7.7" width="4.6" height="4.6" rx="1.2" />,
  },
  // pie with a pulled-out slice
  usage: {
    shape: (
      <>
        <path d="M9 4A7 7 0 1 0 16 11H9z" />
        <path d="M11 2v7h7a7 7 0 0 0-7-7z" />
      </>
    ),
  },
  // info circle
  about: {
    shape: <circle cx="10" cy="10" r="8" />,
    cut: (
      <>
        <circle {...CUT} cx="10" cy="6.3" r="1.15" />
        <rect {...CUT} x="9" y="8.6" width="2" height="5.6" rx="1" />
      </>
    ),
  },
}

/** 20px transparent glyph; `hue` is a CSS variable such as var(--tile-blue) */
export function SideIcon({
  name,
  hue,
}: {
  name: SideIconName
  hue?: string
}) {
  const id = 'si' + useId().replace(/[^a-zA-Z0-9]/g, '')
  const g = GLYPHS[name]
  return (
    <span
      className={`side-ic${hue ? ' side-ic-hue' : ''}`}
      style={hue ? { color: hue } : undefined}
      aria-hidden
    >
      <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
        {g.cut && (
          <mask id={id} maskUnits="userSpaceOnUse" x="0" y="0" width="20" height="20">
            <rect x="0" y="0" width="20" height="20" fill="white" />
            {g.cut}
          </mask>
        )}
        <g mask={g.cut ? `url(#${id})` : undefined}>{g.shape}</g>
      </svg>
    </span>
  )
}

/** layer key -> glyph + hue, shared by the sidebar rows */
export const LAYER_SIDE: Record<string, { icon: SideIconName; hue: string }> = {
  authenticity: { icon: 'authenticity', hue: 'var(--tile-indigo)' },
  support: { icon: 'support', hue: 'var(--tile-blue)' },
  distribution: { icon: 'distribution', hue: 'var(--tile-teal)' },
  norms: { icon: 'norms', hue: 'var(--tile-purple)' },
}
