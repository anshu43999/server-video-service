import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { projectScope } from '../src/api/projectScope'
import type { ManagedSocketOptions } from '../src/api/realtime'
import { alertsApi } from '../src/features/alerts/api'
import { useAlertsStore } from '../src/features/alerts/store'
import { AlertSync } from '../src/features/alerts/sync'
import type { AlertEvent } from '../src/features/alerts/types'

const event = (id: string, projectId = 'a'): AlertEvent => ({ eventId: id, projectId,
  state: 'CONFIRMED', confirmedAtUs: 123, streamId: 'camera-1', origin: 'SERVER_STREAM', disposition: { status: 'OPEN' } })

describe('durable project alert synchronization', () => {
  beforeEach(() => { setActivePinia(createPinia()); projectScope.enable(); projectScope.enter('a') })
  afterEach(() => { projectScope.clear(); projectScope.enabled = false; vi.restoreAllMocks(); vi.useRealTimers() })

  it('baselines history then notifies once across WS, polling and reconnect replay', async () => {
    const list = vi.spyOn(alertsApi, 'list').mockResolvedValue({ events: [event('old')] })
    const store = useAlertsStore()
    await store.refresh()
    expect(store.notifications).toHaveLength(0)
    store.acceptRealtime({ type: 'alert', event: event('new') })
    expect(store.notifications.map((item) => item.eventId)).toEqual(['new'])
    store.dismissNotification('new')
    list.mockResolvedValue({ events: [event('old'), event('new')] })
    await store.refresh({ background: true })
    store.acceptRealtime({ type: 'alert', event: event('new') })
    expect(store.events).toHaveLength(2)
    expect(store.notifications).toHaveLength(0)
    expect(store.events[0].streamId).toBe('camera-1')
  })

  it('catches up missed events from REST when notifications failed', async () => {
    const list = vi.spyOn(alertsApi, 'list').mockResolvedValue({ events: [] })
    const store = useAlertsStore(); await store.refresh()
    list.mockResolvedValue({ events: [event('missed')] })
    await store.refresh({ background: true }); await store.refresh({ background: true })
    expect(store.notifications.map((item) => item.eventId)).toEqual(['missed'])
  })

  it('still announces a new formal websocket event if the initial list read fails', async () => {
    vi.spyOn(alertsApi, 'list').mockRejectedValue(new Error('temporarily unavailable'))
    const store = useAlertsStore(); await store.refresh()
    store.acceptRealtime({ type: 'alert', event: event('live-during-error') })
    expect(store.notifications.map((item) => item.eventId)).toEqual(['live-during-error'])
  })

  it('rejects detections, synthetic probes and wrong-project events', async () => {
    vi.spyOn(alertsApi, 'list').mockResolvedValue({ events: [] })
    const store = useAlertsStore(); await store.refresh()
    expect(store.acceptRealtime({ type: 'detections', event: event('raw') })).toBe(false)
    expect(store.acceptRealtime({ type: 'alert', event: { eventId: 'test-probe', projectId: 'a' } })).toBe(false)
    expect(store.acceptRealtime({ type: 'alert', event: event('wrong', 'b') })).toBe(false)
    expect(store.notifications).toHaveLength(0)
    expect(store.events).toHaveLength(0)
  })

  it('preserves a notification and event received during a stale list request', async () => {
    const list = vi.spyOn(alertsApi, 'list').mockResolvedValue({ events: [] })
    const store = useAlertsStore(); await store.refresh()
    let resolve!: (value: { events: AlertEvent[] }) => void
    list.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const refresh = store.refresh({ background: true })
    store.acceptRealtime({ type: 'alert', event: event('concurrent') })
    resolve({ events: [] }); await refresh
    expect(store.events.map((item) => item.eventId)).toEqual(['concurrent'])
    expect(store.notifications).toHaveLength(1)
  })

  it('clears old-project notices and ignores in-flight old responses on switch', async () => {
    const list = vi.spyOn(alertsApi, 'list').mockResolvedValue({ events: [] })
    const store = useAlertsStore(); await store.refresh()
    store.acceptRealtime({ type: 'alert', event: event('same') })
    let resolve!: (value: { events: AlertEvent[] }) => void
    list.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const refresh = store.refresh()
    projectScope.clear(); projectScope.enter('b')
    resolve({ events: [event('old')] }); await refresh
    expect(store.events).toHaveLength(0); expect(store.notifications).toHaveLength(0)
    list.mockResolvedValue({ events: [event('same', 'b')] }); await store.refresh()
    expect(store.events[0].projectId).toBe('b'); expect(store.notifications).toHaveLength(0)
  })

  it('does not reset an acknowledged event when an old OPEN notification is replayed', async () => {
    vi.spyOn(alertsApi, 'list').mockResolvedValue({ events: [{ ...event('ack'), disposition: { status: 'ACKNOWLEDGED' } }] })
    const store = useAlertsStore(); await store.refresh()
    store.acceptRealtime({ type: 'alert', event: event('ack') })
    expect(store.events[0].disposition?.status).toBe('ACKNOWLEDGED')
    expect(store.notifications).toHaveLength(0)
  })

  it('uses only alert WS/REST, catches up on open and releases timers on revocation', async () => {
    vi.useFakeTimers()
    vi.spyOn(alertsApi, 'list').mockResolvedValue({ events: [] })
    const store = useAlertsStore()
    const refresh = vi.spyOn(store, 'refresh')
    let options!: ManagedSocketOptions<unknown>
    const socket = { start: vi.fn(), stop: vi.fn() }
    const sync = new AlertSync(store, (value) => { options = value; return socket }, 5000)
    await sync.start()
    expect(options.path).toBe('/aiyoloapi/alerts/ws')
    expect(socket.start).toHaveBeenCalledOnce()
    options.onStatus?.('open'); await Promise.resolve()
    await vi.advanceTimersByTimeAsync(5000)
    expect(refresh).toHaveBeenCalledTimes(3)
    projectScope.clear()
    const count = refresh.mock.calls.length
    await vi.advanceTimersByTimeAsync(15000)
    options.onMessage({ type: 'alert', event: event('late') })
    expect(refresh).toHaveBeenCalledTimes(count)
    expect(store.events).toHaveLength(0)
    expect(socket.stop).toHaveBeenCalledOnce()
  })
})
