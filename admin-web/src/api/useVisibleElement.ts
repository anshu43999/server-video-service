import { onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

/** Intersection plus tab visibility. No offscreen preload margin. */
export function useVisibleElement(element: Ref<HTMLElement | undefined>) {
  const visible = ref(false)
  let observer: IntersectionObserver | undefined, intersecting = false
  let generation = 0, disposed = false
  const update = () => { if (!disposed) visible.value = intersecting && document.visibilityState !== 'hidden' }
  const observe = () => {
    if (disposed) return
    const current = ++generation
    observer?.disconnect(); intersecting = false; update()
    if (!element.value) return
    if (typeof IntersectionObserver === 'undefined') { intersecting = true; update(); return }
    const target = element.value
    observer = new IntersectionObserver(entries => {
      if (disposed || current !== generation || element.value !== target) return
      intersecting = entries.some(entry => entry.target === target && entry.isIntersecting); update()
    })
    observer.observe(target)
  }
  onMounted(() => { observe(); document.addEventListener('visibilitychange', update) })
  watch(element, observe, { flush: 'post' })
  onBeforeUnmount(() => { disposed = true; generation++; observer?.disconnect(); document.removeEventListener('visibilitychange', update) })
  return visible
}
