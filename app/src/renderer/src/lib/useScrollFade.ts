import { useCallback, useEffect, useRef, useState } from 'react'

/** Edge-fade state for a scroll container: appends ' can-top' while
    content extends above the viewport and ' can-bottom' while it extends
    below — pair with the .fade-scroll mask in base.css. ResizeObserver
    covers content arriving after mount (list rows, detail switches). */
export function useScrollFade<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [fadeClass, setFadeClass] = useState('')

  const update = useCallback(() => {
    const el = ref.current
    if (!el) return
    const top = el.scrollTop > 1 ? ' can-top' : ''
    const bottom =
      el.scrollTop + el.clientHeight < el.scrollHeight - 1 ? ' can-bottom' : ''
    setFadeClass(top || bottom ? `${top}${bottom}`.trim() : '')
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    update()
    el.addEventListener('scroll', update, { passive: true })
    const ro = new ResizeObserver(update)
    ro.observe(el)
    for (const child of el.children) ro.observe(child)
    return () => {
      el.removeEventListener('scroll', update)
      ro.disconnect()
    }
  }, [update])

  return { ref, fadeClass }
}
