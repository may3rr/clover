// Brand glyphs from LobeHub lobe-icons (MIT) — mono path data recolored
// via the `color` prop (--brand-* tokens live in styles/tokens.css).
import { BRAND_PATHS } from './brandPaths'

interface BrandIconProps {
  size?: number
  color?: string
}

export function BrandIcon({
  name,
  size = 18,
  color = 'currentColor',
}: BrandIconProps & { name: string }) {
  const paths = BRAND_PATHS[name]
  if (!paths) return null
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={color}
      fillRule="evenodd"
      aria-hidden
      style={{ flex: 'none', display: 'block' }}
    >
      {paths.map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  )
}

export function QwenIcon(p: BrandIconProps) {
  return <BrandIcon name="qwen" {...p} />
}
export function OpenAIIcon(p: BrandIconProps) {
  return <BrandIcon name="openai" {...p} />
}
export function DeepSeekIcon(p: BrandIconProps) {
  return <BrandIcon name="deepseek" {...p} />
}
export function OllamaIcon(p: BrandIconProps) {
  return <BrandIcon name="ollama" {...p} />
}
