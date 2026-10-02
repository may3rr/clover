// Inline SVG, SF-Symbols style: filled ".fill" glyphs with
// fill="currentColor" inside colored tiles. Strokes only for chevrons and
// the checkmark draw animation. All colors via CSS variables.

interface IconProps {
  size?: number
  color?: string
}

function Fill({
  size = 18,
  color = 'currentColor',
  children,
  viewBox = '0 0 24 24',
}: IconProps & { children: React.ReactNode; viewBox?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      fill={color}
      aria-hidden
      style={{ flex: 'none', display: 'block' }}
    >
      {children}
    </svg>
  )
}

/** scalloped badge outline for checkmark.seal */
function rosette(
  cx: number,
  cy: number,
  rOut: number,
  rIn: number,
  lobes = 12
): string {
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

// ------------------------------------------------------- filled glyphs

export function TrayFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M4.4 3.5h15.2c.8 0 1.5.5 1.8 1.3l1.5 5.2V18a3 3 0 0 1-3 3H4a3 3 0 0 1-3-3v-8L2.6 4.8a2 2 0 0 1 1.8-1.3zM3.4 11.3h4.5c0 2.1 1.8 3.7 4.1 3.7s4.1-1.6 4.1-3.7h4.5l-1.3-4.8H4.7z"
      />
    </Fill>
  )
}

export function SealCheckFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d={rosette(12, 12, 10, 8.6)} />
      <path
        d="M8.4 12.2l2.4 2.4 4.8-5"
        fill="none"
        stroke="var(--tile-bg, white)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Fill>
  )
}

export function QuoteBubbleFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M12 3.5C6.8 3.5 2.5 7 2.5 11.2c0 2.5 1.3 4.7 3.4 6.2-.2 1.3-.9 2.4-1.8 3.1-.3.3-.1.8.3.8 2.2-.2 4.1-1.1 5.4-2.2.7.1 1.5.2 2.2.2 5.2 0 9.5-3.5 9.5-8S17.2 3.5 12 3.5z" />
      <circle cx="8.3" cy="9.4" r="1.35" fill="var(--tile-bg, white)" />
      <path d="M8.4 10.4l-1.5 3 2.7-.6z" fill="var(--tile-bg, white)" />
      <circle cx="14.2" cy="9.4" r="1.35" fill="var(--tile-bg, white)" />
      <path d="M14.3 10.4l-1.5 3 2.7-.6z" fill="var(--tile-bg, white)" />
    </Fill>
  )
}

export function ChartBarFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <rect x="3.5" y="11" width="4" height="8.5" rx="1.2" />
      <rect x="10" y="4" width="4" height="15.5" rx="1.2" />
      <rect x="16.5" y="7.5" width="4" height="12" rx="1.2" />
    </Fill>
  )
}

export function TextFormatFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M11.5 4.5h1L19 19.5h-2.6l-1.5-4.2H9.1l-1.5 4.2H5zm-1.8 9h4.6L12 7.7z"
      />
    </Fill>
  )
}

export function DocTextFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M6.5 2.5h6.6l5.4 5.4V19a2.5 2.5 0 0 1-2.5 2.5H6.5A2.5 2.5 0 0 1 4 19V5a2.5 2.5 0 0 1 2.5-2.5zM12.6 3.9v4h4z"
      />
      <rect x="8" y="12" width="8" height="1.5" rx="0.75" fill="var(--tile-bg, white)" />
      <rect x="8" y="15.2" width="5.5" height="1.5" rx="0.75" fill="var(--tile-bg, white)" />
    </Fill>
  )
}

export function PlusFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path d="M11 4.5h2V11h6.5v2H13v6.5h-2V13H4.5v-2H11z" />
    </Fill>
  )
}

export function ArrowUpDocFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M6.5 2.5h6.6l5.4 5.4V19a2.5 2.5 0 0 1-2.5 2.5H6.5A2.5 2.5 0 0 1 4 19V5a2.5 2.5 0 0 1 2.5-2.5zM12.6 3.9v4h4z"
      />
      <path
        d="M12 11l3.2 3.2h-2V18h-2.4v-3.8H8.8z"
        fill="var(--tile-bg, white)"
      />
    </Fill>
  )
}

export function ExclaimCircleFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19zM11 6.8h2l-.3 6.4h-1.4zM12 15.6a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5z"
      />
    </Fill>
  )
}

export function ExclaimTriangleFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M12 3.2c.9 0 1.7.5 2.1 1.3l6.6 11.9c.8 1.4-.1 3.1-1.7 3.1H5c-1.6 0-2.5-1.7-1.7-3.1l6.6-11.9c.4-.8 1.2-1.3 2.1-1.3zM11 8.8h2l-.3 4.7h-1.4zM12 15a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6z"
      />
    </Fill>
  )
}

export function InfoCircleFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19zM12 6.6a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6zM10.9 10.6h2.3v6.6h-2.3z"
      />
    </Fill>
  )
}

export function PencilCircleFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19zM16.6 7.4a1.7 1.7 0 0 1 0 2.4l-.8.8-2.4-2.4.8-.8a1.7 1.7 0 0 1 2.4 0zM12.7 9.3l2.4 2.4-5.3 5.3-3 .7.7-3z"
      />
    </Fill>
  )
}

/** doc.text.magnifyingglass — the summary-callout glyph (--accent) */
export function DocMagnifyIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d="M6.5 2.5h6.6l5.4 5.4V19a2.5 2.5 0 0 1-2.5 2.5H6.5A2.5 2.5 0 0 1 4 19V5a2.5 2.5 0 0 1 2.5-2.5zM12.6 3.9v4h4z"
      />
      <rect
        x="7.5"
        y="9"
        width="6"
        height="1.4"
        rx="0.7"
        fill="var(--bg-subtle)"
      />
      {/* magnifier over the bottom-right corner */}
      <circle cx="15.6" cy="15.2" r="4.2" fill="var(--bg-subtle)" />
      <path
        fillRule="evenodd"
        d="M15.6 12a3.2 3.2 0 1 1 0 6.4 3.2 3.2 0 0 1 0-6.4zm0 1.2a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"
      />
      <rect
        x="17.8"
        y="17.4"
        width="1.5"
        height="3.4"
        rx="0.75"
        transform="rotate(-45 17.8 17.4)"
      />
    </Fill>
  )
}

/** done state: filled circle + check that draws via stroke-dashoffset */
export function CheckCircleFillIcon({
  size = 18,
  color = 'var(--ok)',
  draw = false,
}: IconProps & { draw?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden
      style={{ flex: 'none', display: 'block' }}
    >
      <circle cx="12" cy="12" r="9" fill={color} />
      <path
        d="M8 12.4l2.6 2.6L16.4 9.4"
        className={draw ? 'check-draw' : undefined}
        fill="none"
        stroke="var(--bg)"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength={draw ? 100 : undefined}
      />
    </svg>
  )
}

// chevrons stay stroke-only per the spec

export function PersonFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <circle cx="12" cy="7.8" r="4.3" />
      <path d="M12 13.6c-4.5 0-7.7 2.8-7.7 6.1 0 .9.7 1.8 1.6 1.8h12.2c.9 0 1.6-.9 1.6-1.8 0-3.3-3.2-6.1-7.7-6.1z" />
    </Fill>
  )
}

/** gearshape.fill — 8-lobe rosette with a punched centre hole */
export function GearshapeFillIcon(p: IconProps) {
  return (
    <Fill {...p}>
      <path
        fillRule="evenodd"
        d={`${rosette(12, 12, 10.6, 8.1, 8)}M12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8z`}
      />
    </Fill>
  )
}

export function ChevronLeftIcon({ size = 18, color = 'currentColor' }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      style={{ flex: 'none', display: 'block' }}
    >
      <path d="M14.5 5.5 8.5 12l6 6.5" />
    </svg>
  )
}

export function ChevronDownIcon({ size = 18, color = 'currentColor' }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      style={{ flex: 'none', display: 'block' }}
    >
      <path d="M7 9.5 12 14.5 17 9.5" />
    </svg>
  )
}

// ------------------------------------------------------------ tiles

export const LAYER_TILE: Record<string, string> = {
  authenticity: 'var(--tile-indigo)',
  support: 'var(--tile-blue)',
  distribution: 'var(--tile-teal)',
  norms: 'var(--tile-purple)',
}

export const LAYER_FILL_ICONS: Record<
  string,
  (p: IconProps) => React.ReactElement
> = {
  authenticity: SealCheckFillIcon,
  support: QuoteBubbleFillIcon,
  distribution: ChartBarFillIcon,
  norms: TextFormatFillIcon,
}

/** inspector-row severity glyph — filled, semantic graphic colors.
 * The list is already grouped by layer, so rows show the severity, not
 * the layer tile (a green check tile on a problem row reads as "passed") */
export function SevGlyph({
  severity,
  size = 18,
}: {
  severity: string
  size?: number
}) {
  const C = (
    {
      high: ExclaimCircleFillIcon,
      medium: ExclaimTriangleFillIcon,
      low: InfoCircleFillIcon,
      rev: PencilCircleFillIcon,
    } as Record<string, (p: IconProps) => React.ReactElement>
  )[severity] ?? InfoCircleFillIcon
  const color =
    (
      {
        high: 'var(--high)',
        medium: 'var(--medium)',
        low: 'var(--low)',
        rev: 'var(--ok)',
      } as Record<string, string>
    )[severity] ?? 'var(--low)'
  return <C size={size} color={color} />
}

/** colored rounded square with a white filled glyph inside */
export function LayerTile({
  layer,
  size = 20,
  color,
  icon,
}: {
  layer?: string
  size?: number
  color?: string
  icon?: React.ReactNode
}) {
  const Icon = layer ? LAYER_FILL_ICONS[layer] : TrayFillIcon
  const bg = color ?? (layer ? LAYER_TILE[layer] : 'var(--tile-grey)')
  return (
    <span
      className="tile"
      style={
        {
          width: size,
          height: size,
          borderRadius: Math.max(5, Math.round(size * 0.27)),
          background: bg,
          '--tile-bg': bg,
        } as React.CSSProperties
      }
    >
      {icon ?? <Icon size={Math.round(size * 0.62)} />}
    </span>
  )
}

// ------------------------------------------------------ illustrations

/** Empty state: fanned paper sheets with highlighted lines + seal badge */
export function PapersIllustration({
  size = 160,
  active = false,
}: {
  size?: number
  active?: boolean
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 160 160"
      className={active ? 'papers fan' : 'papers'}
      aria-hidden
      style={{ display: 'block' }}
    >
      {/* back sheets */}
      <g className="sheet sheet-b">
        <rect x="30" y="22" width="88" height="114" rx="7"
          fill="var(--bg-subtle)" />
      </g>
      <g className="sheet sheet-c">
        <rect x="44" y="18" width="88" height="114" rx="7"
          fill="var(--fill-strong)" />
      </g>
      {/* front sheet */}
      <g className="sheet sheet-a">
        <rect x="38" y="24" width="90" height="116" rx="7"
          fill="var(--bg)" className="sheet-edge" />
        <g>
          <rect x="50" y="40" width="52" height="5" rx="2.5" fill="var(--fill-strong)" />
          <rect x="50" y="52" width="66" height="4" rx="2" fill="var(--fill)" />
          <rect x="50" y="60" width="40" height="4" rx="2" fill="var(--high-tint)" />
          <rect x="50" y="72" width="66" height="4" rx="2" fill="var(--fill)" />
          <rect x="50" y="80" width="30" height="4" rx="2" fill="var(--medium-tint)" />
          <rect x="50" y="92" width="60" height="4" rx="2" fill="var(--fill)" />
          <rect x="50" y="100" width="34" height="4" rx="2" fill="var(--ok-tint)" />
          <rect x="50" y="112" width="56" height="4" rx="2" fill="var(--fill)" />
          <rect x="50" y="124" width="66" height="4" rx="2" fill="var(--fill)" />
        </g>
      </g>
      {/* accent seal badge */}
      <g className="seal-badge">
        <circle cx="118" cy="122" r="17" fill="var(--accent)" />
        <path
          d="M110 122.4l5.4 5.4 10.6-11"
          fill="none"
          stroke="var(--bg)"
          strokeWidth={2.6}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    </svg>
  )
}

/** 56px filled page icon for the reading view */
export function PageIcon({ size = 56 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 56 56"
      aria-hidden
      style={{ display: 'block', flex: 'none' }}
    >
      <rect x="8" y="4" width="40" height="48" rx="6" fill="var(--accent)" />
      <rect x="16" y="16" width="20" height="3.4" rx="1.7" fill="var(--bg)" />
      <rect x="16" y="24" width="24" height="3" rx="1.5" fill="var(--bg)" opacity="0.85" />
      <rect x="16" y="31" width="24" height="3" rx="1.5" fill="var(--bg)" opacity="0.85" />
      <rect x="16" y="38" width="14" height="3" rx="1.5" fill="var(--bg)" opacity="0.85" />
    </svg>
  )
}

/** empty-filter state: filled checkmark seal in ok colors */
export function SealOkIllustration({ size = 40 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden
      style={{ display: 'block' }}
    >
      <path d={rosette(12, 12, 10, 8.6)} fill="var(--ok)" />
      <path
        d="M8.4 12.2l2.4 2.4 4.8-5"
        fill="none"
        stroke="var(--bg)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
