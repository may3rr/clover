/** View Transition helper — morphs screens via document.startViewTransition
 * where supported; skipped entirely under prefers-reduced-motion. */
interface VT {
  ready: Promise<void>
  finished: Promise<void>
  updateCallbackDone: Promise<void>
}

export function morph(fn: () => void) {
  const d = document as Document & {
    startViewTransition?: (cb: () => void) => VT
  }
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!reduced && typeof d.startViewTransition === 'function') {
    const t = d.startViewTransition(fn)
    // a superseded transition rejects these promises — swallow it
    t.ready.catch(() => {})
    t.finished.catch(() => {})
    t.updateCallbackDone.catch(() => {})
    return
  }
  fn()
}
