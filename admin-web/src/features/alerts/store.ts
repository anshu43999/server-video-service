import { computed, onScopeDispose, ref } from 'vue'
import { projectScope } from '../../api/projectScope'
import { defineStore } from 'pinia'
import { alertsApi } from './api'
import { eventTimestampUs } from './presenters'
import type { AlertEvent, AlertsPhase, DetailPhase, DispositionAction } from './types'
import type { SocketStatus } from '../../api/realtime'

function newestFirst(left: AlertEvent, right: AlertEvent) {
  return (eventTimestampUs(right) ?? 0) - (eventTimestampUs(left) ?? 0)
}

export const useAlertsStore = defineStore('alerts', () => {
  const events = ref<AlertEvent[]>([])
  const phase = ref<AlertsPhase>('idle')
  const error = ref('')
  const selectedId = ref<string | null>(null)
  const detailPhase = ref<DetailPhase>('idle')
  const detailError = ref('')
  const socketStatus = ref<SocketStatus>('idle')
  const notifications = ref<AlertEvent[]>([])
  const seen = new Set<string>()
  const realtimeVersions = new Map<string, number>()
  let realtimeVersion = 0
  let baselineReady = false
  let listSequence = 0
  let detailSequence = 0
  let refreshing: Promise<void> | undefined
  const releaseReset = projectScope.onClear(() => {
    listSequence++; detailSequence++; refreshing = undefined
    events.value = []; phase.value = 'idle'; error.value = ''; closeDetail()
    notifications.value = []; seen.clear(); realtimeVersions.clear()
    baselineReady = false; socketStatus.value = 'idle'
  })
  onScopeDispose(releaseReset)

  const selected = computed(() => events.value.find((event) => event.eventId === selectedId.value) ?? null)
  const openCount = computed(() => events.value.filter((event) => String(event.disposition?.status ?? 'OPEN').toUpperCase() === 'OPEN').length)

  function belongsToProject(event: AlertEvent) {
    return !projectScope.enabled || event.projectId === projectScope.projectId
  }

  function observe(event: AlertEvent, announce: boolean) {
    if (seen.has(event.eventId)) return
    seen.add(event.eventId)
    if (announce && Number(event.confirmedAtUs) > 0 && ['CONFIRMED', 'ENDED'].includes(event.state ?? '')
      && (event.disposition?.status ?? 'OPEN') === 'OPEN') {
      notifications.value = [...notifications.value, event].slice(-3)
    }
  }

  function dismissNotification(eventId: string) {
    notifications.value = notifications.value.filter((event) => event.eventId !== eventId)
  }

  function upsert(event: AlertEvent) {
    const index = events.value.findIndex((item) => item.eventId === event.eventId)
    if (index < 0) events.value = [event, ...events.value].sort(newestFirst)
    else {
      const current = events.value[index]
      events.value[index] = {
        ...current,
        ...event,
        evidence: { ...(current.evidence ?? {}), ...(event.evidence ?? {}) },
        disposition: event.disposition ?? current.disposition,
      }
      events.value = [...events.value].sort(newestFirst)
    }
  }

  async function refresh(options: { background?: boolean } = {}) {
    if (refreshing) return refreshing
    const sequence = ++listSequence
    const versionAtStart = realtimeVersion
    if (!options.background || phase.value === 'idle') phase.value = 'loading'
    error.value = ''
    refreshing = (async () => {
      try {
        const response = await alertsApi.list()
        if (sequence !== listSequence) return
        const merged = new Map(response.events.filter(belongsToProject).map((event) => [event.eventId, event]))
        // A slow list response must not erase newer websocket facts.
        for (const event of events.value) {
          if ((realtimeVersions.get(event.eventId) ?? 0) > versionAtStart) merged.set(event.eventId, event)
        }
        events.value = [...merged.values()].sort(newestFirst)
        for (const event of events.value) observe(event, baselineReady)
        baselineReady = true
        phase.value = 'ready'
      } catch (reason) {
        if (sequence !== listSequence) return
        phase.value = events.value.length && options.background ? 'ready' : 'error'
        error.value = reason instanceof Error ? reason.message : '无法读取告警事件'
      }
    })().finally(() => { if (sequence === listSequence) refreshing = undefined })
    return refreshing
  }

  async function openDetail(eventId: string) {
    selectedId.value = eventId
    detailPhase.value = 'loading'
    detailError.value = ''
    const sequence = ++detailSequence
    const eventResult = await Promise.resolve().then(() => alertsApi.get(eventId)).then(
      value => ({ status: 'fulfilled' as const, value }),
      reason => ({ status: 'rejected' as const, reason }),
    )
    if (sequence !== detailSequence || selectedId.value !== eventId) return
    if (eventResult.status === 'fulfilled') {
      upsert(eventResult.value)
      detailPhase.value = 'ready'
    } else {
      detailPhase.value = 'error'
      detailError.value = eventResult.reason instanceof Error ? eventResult.reason.message : '无法读取事件详情'
    }
  }

  function closeDetail() {
    detailSequence += 1
    selectedId.value = null
    detailPhase.value = 'idle'
    detailError.value = ''
  }

  async function dispose(eventId: string, action: DispositionAction, note?: string) {
    const generation = projectScope.generation
    const expectedRevision = events.value.find((event) => event.eventId === eventId)?.dispositionRevision ?? 0
    const updated = await alertsApi.disposition(eventId, action, note, expectedRevision)
    projectScope.assertCurrent(generation)
    upsert(updated)
    return updated
  }

  function acceptRealtime(message: unknown) {
    if (!message || typeof message !== 'object') return false
    const record = message as { type?: unknown; event?: unknown }
    if (record.type !== 'alert' || !record.event || typeof record.event !== 'object') return false
    const event = record.event as AlertEvent
    if (typeof event.eventId !== 'string' || !event.eventId.trim() || !belongsToProject(event)) return false
    const current = events.value.find((item) => item.eventId === event.eventId)
    const merged = { ...current, ...event }
    if (!current && (!(Number(event.confirmedAtUs) > 0) || !['CONFIRMED', 'ENDED'].includes(event.state ?? ''))) return false
    // An old replayed OPEN snapshot cannot undo a human disposition.
    if (current?.disposition && current.disposition.status !== 'OPEN' && event.disposition?.status === 'OPEN') {
      merged.disposition = current.disposition
    }
    upsert(merged)
    realtimeVersions.set(event.eventId, ++realtimeVersion)
    // A live, confirmed event must still notify if the initial REST read failed.
    observe(merged, true)
    return true
  }

  return {
    events, phase, error, selectedId, selected, detailPhase, detailError, openCount,
    refresh, openDetail, closeDetail, dispose, acceptRealtime,
    notifications, dismissNotification, socketStatus,
  }
})
