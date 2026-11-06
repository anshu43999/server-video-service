import { onBeforeUnmount, ref, shallowRef } from 'vue'
import { ApiError } from '../../api/errors'
import { projectScope } from '../../api/projectScope'
import { managementError } from './api'

/** Component-local state: never persists business data or replays uncertain writes. */
export function useManagement<T>(initial: T, load: (signal: AbortSignal) => Promise<T>) {
  const data = shallowRef<T>(initial), loading = ref(false), error = ref(''), notice = ref('')
  const busy = ref(false), mutationError = ref(''), needsReload = ref(false)
  let disposed = false, readSequence = 0, reader: AbortController | undefined, writer: AbortController | undefined
  async function refresh() {
    const seq = ++readSequence, generation = projectScope.generation
    reader?.abort(); reader = new AbortController(); loading.value = true; error.value = ''
    try {
      const value = await load(reader.signal)
      if (disposed || seq !== readSequence || generation !== projectScope.generation) return false
      data.value = value; needsReload.value = false; return true
    } catch (e) { if (!disposed && seq === readSequence && generation === projectScope.generation) { data.value = initial; error.value = managementError(e) }; return false }
    finally { if (!disposed && seq === readSequence) loading.value = false }
  }
  function resetMutation() { mutationError.value = ''; notice.value = '' }
  async function run(action: (signal: AbortSignal) => Promise<unknown>, success: () => void | Promise<void>) {
    if (busy.value || needsReload.value) return
    busy.value = true; mutationError.value = ''; writer = new AbortController()
    const generation = projectScope.generation
    try {
      await action(writer.signal)
      if (disposed || generation !== projectScope.generation) return
      notice.value = '操作已由服务器确认。'; await success()
      if (!disposed && generation === projectScope.generation) await refresh()
    } catch (e) {
      if (disposed || generation !== projectScope.generation) return
      needsReload.value = e instanceof ApiError && (e.status === 409 || (e.status ?? 0) >= 500 || ['network', 'timeout', 'invalid-response'].includes(e.kind))
      mutationError.value = managementError(e) + (needsReload.value ? ' 请关闭弹窗并刷新核验后再操作；不会自动重试。' : '')
    } finally { if (!disposed) busy.value = false }
  }
  onBeforeUnmount(() => { disposed = true; readSequence++; reader?.abort(); writer?.abort(); data.value = initial })
  return { data, loading, error, notice, busy, mutationError, needsReload, refresh, run, resetMutation }
}
