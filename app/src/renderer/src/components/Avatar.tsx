import type { Prefs } from '../lib/prefs'

/** Rounded user avatar: a picked image, or the first character of the
 *  name on a --tile-* hue. All colours stay on CSS variables. */
export default function Avatar({
  prefs,
  size = 24,
}: {
  prefs: Prefs
  size?: number
}) {
  const a = prefs.avatar
  if (a.kind === 'image' && a.image) {
    return (
      <img
        className="avatar"
        src={a.image}
        alt=""
        style={{ width: size, height: size }}
      />
    )
  }
  const name = prefs.name.trim()
  const initial = name ? Array.from(name)[0] : ''
  return (
    <span
      className="avatar"
      style={{
        width: size,
        height: size,
        background: `var(--tile-${a.color})`,
        fontSize: Math.max(13, Math.round(size * 0.46)),
      }}
      aria-hidden
    >
      {initial}
    </span>
  )
}
