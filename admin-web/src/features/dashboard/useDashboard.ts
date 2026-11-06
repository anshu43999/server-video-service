import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { ApiError } from '../../api/errors'
import { alertsApi } from '../alerts/api'
import type { AlertEvent } from '../alerts/types'
import { streamsApi } from '../streams/api'
import type { StreamItem } from '../streams/types'
import { dashboardApi } from './api'
import { useProjectCapabilities } from '../projects/capabilities'
import type { DashboardStats, StatsRange } from './types'

export function useDashboard(range: Ref<StatsRange>) {
  const { can } = useProjectCapabilities()
  const stats = ref<DashboardStats | null>(null), streams = ref<StreamItem[] | null>(null), events = ref<AlertEvent[] | null>(null)
  const statsError = ref(''), streamsError = ref(''), eventsError = ref(''), loading = ref(false)
  let controller: AbortController | undefined, timer: ReturnType<typeof setTimeout> | undefined, disposed = false
  const message = (error: unknown) => error instanceof ApiError ? error.message : '读取失败，请稍后重试'
  async function refresh() {
    if (disposed) return
    if (timer) clearTimeout(timer)
    controller?.abort()
    controller = new AbortController()
    const signal = controller.signal, requestedRange = range.value
    loading.value = true
    // Each source resolves independently; one failed endpoint must not hide another source.
    async function read<T>(request: Promise<T>, target: Ref<T | null>, error: Ref<string>) {
      try { const value = await request; if (!disposed && !signal.aborted) { target.value = value; error.value = '' } }
      catch (reason) { if (!disposed && !signal.aborted) { target.value = null; error.value = message(reason) } }
    }
    await Promise.all([
      read(dashboardApi.stats(requestedRange, signal), stats, statsError),
      can('project.streams.view') ? read(streamsApi.list(signal), streams, streamsError) : (streams.value = []),
      read(alertsApi.recent(signal).then(result => result.events), events, eventsError),
    ])
    if (disposed || signal.aborted) return
    loading.value = false
    timer = setTimeout(() => { void refresh() }, 10_000)
  }
  watch(range, () => { stats.value = null; statsError.value = ''; void refresh() }, { immediate: true })
  onBeforeUnmount(() => { disposed = true; controller?.abort(); if (timer) clearTimeout(timer) })
  return { stats, streams, events, statsError, streamsError, eventsError, loading, refresh }
}
