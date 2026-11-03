/** Bring an element to the top of the screen; no animation for people whose system asks for less motion. */
export function bringIntoView(el: HTMLElement | null): void {
  if (!el) return
  let calm = false
  try {
    calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    /* assume motion is fine */
  }
  el.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'start' })
}
