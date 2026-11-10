import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { ApiError } from '../../api/errors'
import { projectScope } from '../../api/projectScope'
import { dashboardReads } from '../../api/readCache'
import { useSessionStore } from '../../stores/session'
import { useProjectsStore } from '../../stores/projects'
import { alertsApi } from '../alerts/api'
import type { AlertEvent } from '../alerts/types'
import { streamsApi } from '../streams/api'
import type { StreamItem } from '../streams/types'
import { dashboardApi } from './api'
import { useProjectCapabilities } from '../projects/capabilities'
import type { DashboardStats, StatsRange } from './types'

export function useDashboard(range: Ref<StatsRange>) {
  const { can } = useProjectCapabilities(), session = useSessionStore(), projects = useProjectsStore()
  // Identity, scope, permission revision and query are part of every cache key.
  const context = () => JSON.stringify([session.user?.accountId, session.user?.role, session.user?.platformRole,
    projectScope.generation, projectScope.enabled, projects.current?.projectId ?? 'platform',
    projects.current?.revision, projects.current?.membershipRevision, projects.current?.capabilities])
  const stats = ref<DashboardStats | null>(null), streams = ref<StreamItem[] | null>(null), events = ref<AlertEvent[] | null>(null)
  const statsError = ref(''), streamsError = ref(''), eventsError = ref(''), loading = ref(false)
  let statsController: AbortController | undefined, sourcesController: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined, disposed = false, sequence = 0, refreshSequence = 0
  const message = (error: unknown) => error instanceof ApiError ? error.message : '读取失败，请稍后重试'
  async function read<T>(tag: string, parameters: string, load: (signal: AbortSignal) => Promise<T>, signal: AbortSignal, target: Ref<T | null>, error: Ref<string>) {
    const identity = context()
    try {
      const value = await dashboardReads.read(identity, tag, parameters, load, signal)
      if (!disposed && !signal.aborted && identity === context()) { target.value = value; error.value = '' }
    } catch (reason) {
      if (reason instanceof ApiError && reason.kind === 'cancelled') return
      if (!disposed && !signal.aborted && identity === context()) { target.value = null; error.value = message(reason) }
    }
  }
  async function refreshStats() {
    const run = ++sequence
    statsController?.abort(); statsController = new AbortController()
    const requestedRange = range.value
    loading.value = true
    await read('stats', requestedRange, signal => dashboardApi.stats(requestedRange, signal), statsController.signal, stats, statsError)
    if (!disposed && run === sequence) loading.value = false
  }
  async function refreshSources() {
    sourcesController?.abort(); sourcesController = new AbortController()
    const signal = sourcesController.signal
    await Promise.all([
      can('project.streams.view') ? read('streams', '', streamsApi.list, signal, streams, streamsError) : (streams.value = []),
      // The WS store is not a complete recent window; retain the authoritative query.
      read('recent', 'limit=20', signal => alertsApi.recent(signal).then(result => result.events), signal, events, eventsError),
    ])
  }
  async function refresh(force = true) {
    if (disposed) return
    const run = ++refreshSequence
    if (timer) clearTimeout(timer)
    if (force) dashboardReads.invalidate(['stats', 'streams', 'recent'])
    await Promise.all([refreshStats(), refreshSources()])
    if (!disposed && run === refreshSequence) {
      // A layout switch must not extend a nearly expired snapshot another 10s.
      const deadlines = [['stats', range.value], ['streams', ''], ['recent', 'limit=20']] as const
      const remaining = deadlines.map(([tag, parameters]) => dashboardReads.remaining(context(), tag, parameters) ?? 10_000)
      timer = setTimeout(() => { void refresh(false) }, Math.min(10_000, ...remaining))
    }
  }
  watch(range, () => { if (!disposed) { stats.value = null; statsError.value = ''; void refreshStats() } })
  void refresh(false)
  const stop = () => {
    disposed = true; sequence++; statsController?.abort(); sourcesController?.abort()
    if (timer) clearTimeout(timer)
    stats.value = null; streams.value = null; events.value = null
  }
  const release = projectScope.register(stop)
  onBeforeUnmount(() => { release(); stop() })
  return { stats, streams, events, statsError, streamsError, eventsError, loading, refresh: () => refresh(true) }
}
