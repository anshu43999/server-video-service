import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ManagedWebSocket, subscriptionRegistry, websocketUrl } from '../src/api/realtime'
import { bindSocketLifecycle } from '../src/api/useManagedWebSocket'

class FakeSocket {
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  close = vi.fn()
  open() { this.onopen?.({} as Event) }
  message(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent) }
  closed(code: number) { this.onclose?.({ code } as CloseEvent) }
}

const locationLike = { protocol: 'https:', host: 'admin.example:8443' } as Location

describe('ManagedWebSocket', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => { subscriptionRegistry.closeAll(); vi.useRealTimers() })

  it('uses same-origin cookie-compatible URLs, parses messages and releases on stop', () => {
    expect(websocketUrl('/aiyoloapi/alerts/ws', locationLike)).toBe('wss://admin.example:8443/aiyoloapi/alerts/ws')
    expect(() => websocketUrl('wss://outside/ws', locationLike)).toThrow()
    const sockets: FakeSocket[] = []
    const messages: unknown[] = []
    const statuses: string[] = []
    const managed = new ManagedWebSocket({
      path: '/aiyoloapi/alerts/ws', location: locationLike,
      createSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket },
      onMessage: (message) => messages.push(message), onStatus: (status) => statuses.push(status),
    })
    managed.start(); sockets[0].open(); sockets[0].message({ type: 'alert', event: { eventId: 'e-1' } })
    expect(messages).toEqual([{ type: 'alert', event: { eventId: 'e-1' } }])
    expect(statuses).toEqual(['connecting', 'open'])
    expect(subscriptionRegistry.size).toBe(1)
    managed.stop()
    expect(sockets[0].close).toHaveBeenCalledWith(1000, 'client stopped')
    expect(subscriptionRegistry.size).toBe(0)
  })

  it('reconnects with bounded exponential backoff and respects offline state', () => {
    const sockets: FakeSocket[] = []
    const retries: number[] = []
    const managed = new ManagedWebSocket({
      path: '/aiyoloapi/alerts/ws', location: locationLike, random: () => 0,
      baseDelayMs: 100, maxDelayMs: 150, maxReconnectAttempts: 3,
      createSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket },
      onMessage: () => {}, onStatus: (status, delay) => { if (status === 'backoff') retries.push(delay!) },
    })
    managed.start(); sockets[0].closed(1006)
    expect(retries).toEqual([75])
    vi.advanceTimersByTime(75); expect(sockets).toHaveLength(2)
    sockets[1].closed(1006); vi.advanceTimersByTime(150); expect(sockets).toHaveLength(3)
    expect(retries.every((delay) => delay <= 150)).toBe(true)
    managed.setOnline(false); vi.runOnlyPendingTimers(); expect(sockets).toHaveLength(3)
    managed.setOnline(true); expect(sockets).toHaveLength(4)
  })

  it('binds start and cleanup to component lifecycle', () => {
    const socket = { start: vi.fn(), stop: vi.fn() }
    let mount = () => {}; let unmount = () => {}
    bindSocketLifecycle(socket, (callback) => { mount = callback }, (callback) => { unmount = callback })
    mount(); unmount()
    expect(socket.start).toHaveBeenCalledOnce()
    expect(socket.stop).toHaveBeenCalledOnce()
  })

  it('ignores late open and close callbacks from an old connection', () => {
    const sockets: FakeSocket[] = []
    const statuses: string[] = []
    const managed = new ManagedWebSocket({
      path: '/aiyoloapi/alerts/ws', location: locationLike,
      createSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket },
      onMessage: () => {}, onStatus: status => statuses.push(status),
    })
    managed.start(); sockets[0].open()
    managed.setOnline(false); managed.setOnline(true); sockets[1].open()
    const count = statuses.length
    sockets[0].open(); sockets[0].closed(4401)
    vi.runOnlyPendingTimers()
    expect(statuses).toHaveLength(count)
    expect(sockets).toHaveLength(2)
    expect(subscriptionRegistry.size).toBe(1)
  })

  it.each([[4401, 'auth-failed'], [4404, 'missing'], [4429, 'rate-limited']] as const)(
    'stops terminal close code %i as %s', (code, expectedStatus) => {
      const socket = new FakeSocket()
      const statuses: string[] = []
      const terminal = vi.fn()
      const managed = new ManagedWebSocket({
        path: '/aiyoloapi/streams/one/detections', location: locationLike,
        createSocket: () => socket, onMessage: () => {}, onStatus: (status) => statuses.push(status), onTerminal: terminal,
      })
      managed.start(); socket.closed(code); vi.runOnlyPendingTimers()
      expect(statuses).toContain(expectedStatus)
      expect(terminal).toHaveBeenCalledWith(code)
      expect(subscriptionRegistry.size).toBe(0)
    },
  )
})
