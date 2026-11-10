import { onBeforeUnmount, ref, shallowRef, watch, type Ref } from 'vue'
import { projectScope } from '../../api/projectScope'
import { managementError } from './api'

/** Form-local candidates: read on opening, cancel on close, never reuse for authorization. */
export function useCandidates<T>(visible: Ref<boolean>, load: (signal: AbortSignal) => Promise<T[]>) {
  const data = shallowRef<T[]>([]), loading = ref(false), error = ref('')
  let controller: AbortController | undefined, sequence = 0, disposed = false
  const clear = () => { sequence++; controller?.abort(); controller = undefined; data.value = []; error.value = ''; loading.value = false }
  async function refresh() {
    if (!visible.value || disposed) return
    clear(); const run = sequence, generation = projectScope.generation
    controller = new AbortController(); const signal = controller.signal
    loading.value = true
    try {
      const result = await load(signal)
      if (!disposed && !signal.aborted && run === sequence && generation === projectScope.generation) data.value = result
    } catch (reason) {
      if (!disposed && !signal.aborted && run === sequence && generation === projectScope.generation) error.value = managementError(reason)
    } finally { if (!disposed && run === sequence) loading.value = false }
  }
  watch(visible, value => { if (value) void refresh(); else clear() }, { immediate: true })
  const release = projectScope.onClear(() => { disposed = true; clear() })
  onBeforeUnmount(() => { disposed = true; release(); clear() })
  return { data, loading, error, refresh }
}
