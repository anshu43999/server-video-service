import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ApiError } from '../../api/errors'
import { projectScope } from '../../api/projectScope'
import { managementReads } from '../../api/readCache'
import { managementError } from './api'

/** Component-local state: never persists business data or replays uncertain writes. */
export function useManagement<T>(initial: T, load: (signal: AbortSignal) => Promise<T>, cache?: { context: () => string; tag: string; parameters?: string }) {
  const data = shallowRef<T>(initial), loading = ref(false), error = ref(''), notice = ref('')
  const busy = ref(false), mutationError = ref(''), needsReload = ref(false)
  let disposed = false, readSequence = 0, reader: AbortController | undefined, writer: AbortController | undefined
  let inFlight: Promise<boolean> | undefined, readingContext: string | undefined
  function refresh(force = true): Promise<boolean> {
    if (disposed) return Promise.resolve(false)
    const identity = cache?.context()
    if (cache && inFlight && readingContext === identity && !reader?.signal.aborted) return inFlight
    const pending = read(force, identity).finally(() => { if (inFlight === pending) inFlight = undefined })
    readingContext = identity; inFlight = pending
    return pending
  }
  async function read(force: boolean, identity: string | undefined) {
    const seq = ++readSequence, generation = projectScope.generation
    reader?.abort(); reader = new AbortController(); loading.value = true; error.value = ''
    const signal = reader.signal
    if (cache && force) managementReads.invalidate([cache.tag])
    try {
      const value = cache ? await managementReads.read(identity!, cache.tag, cache.parameters ?? '', load, signal) : await load(signal)
      if (disposed || signal.aborted || seq !== readSequence || generation !== projectScope.generation || (cache && identity !== cache.context())) return false
      data.value = value; needsReload.value = false; return true
    } catch (e) {
      if (!disposed && seq === readSequence && generation === projectScope.generation) {
        data.value = initial
        if (!(e instanceof ApiError && e.kind === 'cancelled')) error.value = managementError(e)
      }
      return false
    }
    finally { if (!disposed && seq === readSequence) loading.value = false }
  }
  function resetMutation() { mutationError.value = ''; notice.value = '' }
  async function run(action: (signal: AbortSignal) => Promise<unknown>, success: () => void | Promise<void>, refreshAfterWrite = true) {
    if (busy.value || needsReload.value) return
    if (cache) {
      reader?.abort(); readSequence++; inFlight = undefined; loading.value = false
      managementReads.invalidate([cache.tag])
    }
    busy.value = true; mutationError.value = ''; writer = new AbortController()
    const generation = projectScope.generation
    try {
      await action(writer.signal)
      if (disposed || generation !== projectScope.generation) return
      notice.value = '操作已由服务器确认。'; await success()
      if (refreshAfterWrite && !disposed && generation === projectScope.generation) await refresh()
    } catch (e) {
      if (disposed || generation !== projectScope.generation) return
      needsReload.value = e instanceof ApiError && (e.status === 409 || (e.status ?? 0) >= 500 || ['network', 'timeout', 'invalid-response'].includes(e.kind))
      mutationError.value = managementError(e) + (needsReload.value ? ' 请关闭弹窗并刷新核验后再操作；不会自动重试。' : '')
    } finally { if (!disposed) busy.value = false }
  }
  // The platform permission list can change without remounting the shell. Never
  // keep a private snapshot associated with the previous identity/revision key.
  if (cache) watch(cache.context, () => {
    readSequence++; reader?.abort(); managementReads.invalidate(); data.value = initial; loading.value = false
    if (!disposed) void refresh(true)
  }, { flush: 'sync' })
  const stop = () => { disposed = true; readSequence++; reader?.abort(); writer?.abort(); data.value = initial; loading.value = false }
  const release = projectScope.register(stop)
  onBeforeUnmount(() => { release(); stop() })
  return { data, loading, error, notice, busy, mutationError, needsReload, refresh: () => refresh(true), loadInitial: () => refresh(false), run, resetMutation }
}
