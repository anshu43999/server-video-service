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

  it('REST recovers end and human disposition updates that are not broadcast', async () => {
    const list = vi.spyOn(alertsApi, 'list').mockResolvedValue({ events: [event('updated')] })
    const store = useAlertsStore(); await store.refresh()
    list.mockResolvedValue({ events: [{ ...event('updated'), state: 'ENDED', endedAtUs: 456,
      dispositionRevision: 1, disposition: { status: 'ACKNOWLEDGED' } }] })
    await store.refresh({ background: true })
    expect(store.events[0].state).toBe('ENDED')
    expect(store.events[0].disposition?.status).toBe('ACKNOWLEDGED')
    expect(store.events[0].dispositionRevision).toBe(1)
    expect(store.notifications).toHaveLength(0)
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

  function setupSync() {
    vi.useFakeTimers()
    const store = { refresh: vi.fn<() => Promise<void>>().mockResolvedValue(), acceptRealtime: vi.fn(), socketStatus: 'idle' as const }
    const options: ManagedSocketOptions<unknown>[] = []
    const socket = { start: vi.fn(), stop: vi.fn() }
    const sync = new AlertSync(store, (value) => { options.push(value); return socket })
    return { store, options, socket, sync }
  }

  it('retains 5s compensation when WS is open because coverage is incomplete', async () => {
    const { store, options, sync } = setupSync()
    await sync.start(); options[0].onStatus?.('open')
    await vi.advanceTimersByTimeAsync(0)
    const before = store.refresh.mock.calls.length
    await vi.advanceTimersByTimeAsync(60_000)
    expect(store.refresh).toHaveBeenCalledTimes(before + 12)
  })

  it('reconciles on disconnect and recovery and resets the compensation deadline', async () => {
    const { store, options, sync } = setupSync()
    await sync.start(); options[0].onStatus?.('open'); await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(4900)
    options[0].onStatus?.('backoff'); await vi.advanceTimersByTimeAsync(0)
    expect(store.refresh).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(100)
    expect(store.refresh).toHaveBeenCalledTimes(3) // no redundant old 5s timer
    options[0].onStatus?.('connecting'); options[0].onStatus?.('open')
    await vi.advanceTimersByTimeAsync(0)
    expect(store.refresh).toHaveBeenCalledTimes(4)
    options[0].onStatus?.('open'); await vi.advanceTimersByTimeAsync(0)
    expect(store.refresh).toHaveBeenCalledTimes(4)
  })

  it('coalesces reconnect bursts into one fresh read after an old in-flight snapshot', async () => {
    vi.useFakeTimers()
    const list = vi.spyOn(alertsApi, 'list').mockResolvedValue({ events: [] })
    const store = useAlertsStore()
    let options!: ManagedSocketOptions<unknown>
    const sync = new AlertSync(store, (value) => { options = value; return { start: vi.fn(), stop: vi.fn() } })
    await sync.start(); options.onStatus?.('open'); await vi.advanceTimersByTimeAsync(0)
    let release!: (value: { events: AlertEvent[] }) => void
    list.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    await vi.advanceTimersByTimeAsync(5000)
    for (let i = 0; i < 3; i++) { options.onStatus?.('backoff'); options.onStatus?.('open') }
    await vi.advanceTimersByTimeAsync(20_000)
    expect(list).toHaveBeenCalledTimes(3)
    list.mockResolvedValue({ events: [event('missed-during-flight')] })
    release({ events: [] }); await vi.advanceTimersByTimeAsync(0)
    expect(list).toHaveBeenCalledTimes(4)
    expect(store.events.map(value => value.eventId)).toEqual(['missed-during-flight'])
    expect(store.notifications).toHaveLength(1)
  })

  it('continues REST when reconnect attempts stop without terminal authorization failure', async () => {
    const { store, options, sync } = setupSync()
    await sync.start(); options[0].onStatus?.('open'); await vi.advanceTimersByTimeAsync(0)
    options[0].onStatus?.('stopped'); await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(5000)
    expect(store.refresh).toHaveBeenCalledTimes(4)
  })

  it.each([4401, 4403, 4404, 4429])('terminal %s stops queued reconciliation and polling', async code => {
    const { store, options, sync } = setupSync()
    await sync.start()
    options[0].onStatus?.('open')
    options[0].onTerminal?.(code)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(store.refresh).toHaveBeenCalledOnce()
  })

  it('ignores terminal callbacks from an earlier sync generation', async () => {
    const { store, options, sync } = setupSync()
    await sync.start(); await sync.start()
    options[0].onTerminal?.(4403)
    await vi.advanceTimersByTimeAsync(5000)
    expect(store.refresh).toHaveBeenCalledTimes(3)
  })

  it('does not revive queued reads when a pending snapshot settles after revocation', async () => {
    const { store, options, sync } = setupSync()
    await sync.start()
    let release!: () => void
    store.refresh.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    options[0].onStatus?.('open'); await vi.advanceTimersByTimeAsync(0)
    options[0].onStatus?.('backoff'); options[0].onStatus?.('open')
    projectScope.clear(); release(); await vi.advanceTimersByTimeAsync(60_000)
    expect(store.refresh).toHaveBeenCalledTimes(2)
  })

  it('recovers after rejected reads without unhandled promises or overlapping timers', async () => {
    const { store, options, sync } = setupSync()
    store.refresh.mockRejectedValueOnce(new Error('temporary'))
    await sync.start()
    store.refresh.mockRejectedValueOnce(new Error('temporary'))
    options[0].onStatus?.('open'); options[0].onStatus?.('backoff')
    await vi.advanceTimersByTimeAsync(0)
    expect(store.refresh).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(5000)
    expect(store.refresh).toHaveBeenCalledTimes(4)
  })
})
