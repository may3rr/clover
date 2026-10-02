/** View Transition helper — morphs screens via document.startViewTransition
 * where supported; skipped entirely under prefers-reduced-motion. */
export function morph(fn: () => void) {
  const d = document as Document & {
    startViewTransition?: (cb: () => void) => unknown
  }
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!reduced && typeof d.startViewTransition === 'function') {
    d.startViewTransition(fn)
    return
  }
  fn()
}
