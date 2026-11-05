/** Platform of the renderer, read from the user agent so the landing
 *  page's web replica works without the preload bridge. */
export const IS_WIN =
  typeof navigator !== 'undefined' && /Windows/.test(navigator.userAgent)

/** A shortcut written the macOS way (⌘⇧\) in this platform's notation:
 *  Ctrl+Shift+\ on Windows. */
export function keys(mac: string): string {
  if (!IS_WIN) return mac
  const mods: string[] = []
  let rest = mac
  for (;;) {
    const c = rest[0]
    if (c === '⌘') mods.push('Ctrl')
    else if (c === '⇧') mods.push('Shift')
    else if (c === '⌥') mods.push('Alt')
    else break
    rest = rest.slice(1)
  }
  return [...mods, rest].join('+')
}
