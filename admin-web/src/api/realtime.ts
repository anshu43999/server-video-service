import { projectScope } from './projectScope'
export type SocketStatus = 'idle' | 'connecting' | 'open' | 'offline' | 'backoff' | 'stopped' | 'auth-failed' | 'missing' | 'rate-limited'

interface WebSocketLike {
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  onerror: ((event: Event) => void) | null
  close(code?: number, reason?: string): void
}

export interface ManagedSocketOptions<T> {
  path: string
  onMessage: (message: T) => void
  onStatus?: (status: SocketStatus, retryMs?: number) => void
  onTerminal?: (code: number) => void
  createSocket?: (url: string) => WebSocketLike
  random?: () => number
  baseDelayMs?: number
  maxDelayMs?: number
  maxReconnectAttempts?: number
  location?: Pick<Location, 'protocol' | 'host'>
}

export function websocketUrl(path: string, locationLike: Pick<Location, 'protocol' | 'host'> = globalThis.location) {
  if (!path.startsWith('/aiyoloapi/') || path.includes('://')) throw new TypeError('WebSocket path must stay under /aiyoloapi')
  return `${locationLike.protocol === 'https:' ? 'wss:' : 'ws:'}//${locationLike.host}${path}`
}

class SubscriptionRegistry {
  private readonly subscriptions = new Set<{ stop: () => void }>()
  add(value: { stop: () => void }) { this.subscriptions.add(value) }
  delete(value: { stop: () => void }) { this.subscriptions.delete(value) }
  closeAll() {
    for (const subscription of [...this.subscriptions]) subscription.stop()
    this.subscriptions.clear()
  }
  get size() { return this.subscriptions.size }
}

export const subscriptionRegistry = new SubscriptionRegistry()

export class ManagedWebSocket<T = unknown> {
  private socket?: WebSocketLike
  private timer?: ReturnType<typeof setTimeout>
  private attempts = 0
  private stopped = true
  private unregister?: () => void
  private projectGeneration = 0
  private online = typeof navigator === 'undefined' || navigator.onLine !== false
  private readonly onlineListener = () => this.setOnline(true)
  private readonly offlineListener = () => this.setOnline(false)

  constructor(private readonly options: ManagedSocketOptions<T>) {}

  start() {
    if (!this.stopped) return
    this.stopped = false
    this.projectGeneration = projectScope.generation
    this.unregister = projectScope.enabled ? projectScope.register(() => this.stop()) : undefined
    subscriptionRegistry.add(this)
    if (typeof window !== 'undefined') {
      window.addEventListener('online', this.onlineListener)
      window.addEventListener('offline', this.offlineListener)
    }
    this.connect()
  }

  stop() {
    this.unregister?.(); this.unregister = undefined
    this.stopped = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = undefined
    const socket = this.socket
    this.socket = undefined
    if (socket) {
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null
      socket.close(1000, 'client stopped')
    }
    if (typeof window !== 'undefined') {
      window.removeEventListener('online', this.onlineListener)
      window.removeEventListener('offline', this.offlineListener)
    }
    subscriptionRegistry.delete(this)
    this.status('stopped')
  }

  setOnline(online: boolean) {
    this.online = online
    if (!online) {
      if (this.timer) clearTimeout(this.timer)
      this.timer = undefined
      this.socket?.close(1000, 'offline')
      this.socket = undefined
      this.status('offline')
    } else if (!this.stopped && !this.socket && !this.timer) {
      this.attempts = 0
      this.connect()
    }
  }

  private connect() {
    if (this.stopped || !this.online || this.socket) return
    this.status('connecting')
    const create = this.options.createSocket ?? ((url: string) => new WebSocket(url))
    let path: string
    try { path = projectScope.path(this.options.path); projectScope.assertCurrent(this.projectGeneration) }
    catch { this.stop(); return }
    const socket = create(websocketUrl(path, this.options.location ?? globalThis.location))
    this.socket = socket
    socket.onopen = () => {
      if (this.stopped || this.socket !== socket) return
      this.attempts = 0; this.status('open')
    }
    socket.onmessage = (event) => {
      if (this.stopped || this.socket !== socket || (projectScope.enabled && this.projectGeneration !== projectScope.generation)) return
      try { this.options.onMessage(JSON.parse(String(event.data)) as T) } catch { /* Invalid messages do not poison the connection. */ }
    }
    socket.onerror = () => { /* close owns reconnect policy */ }
    socket.onclose = (event) => {
      if (this.socket !== socket) return
      this.socket = undefined
      if (this.stopped) return
      const terminal: Partial<Record<number, SocketStatus>> = { 4401: 'auth-failed', 4403: 'auth-failed', 4404: 'missing', 4429: 'rate-limited' }
      const terminalStatus = terminal[event.code]
      if (terminalStatus) {
        this.status(terminalStatus)
        this.options.onTerminal?.(event.code)
        this.stopWithoutStatus()
        if ([4401, 4403, 4404].includes(event.code)) projectScope.onDenied?.()
        return
      }
      if (!this.online) { this.status('offline'); return }
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect() {
    const maxAttempts = this.options.maxReconnectAttempts ?? 8
    if (this.attempts >= maxAttempts) { this.stop(); return }
    const base = this.options.baseDelayMs ?? 500
    const ceiling = this.options.maxDelayMs ?? 15_000
    const jitter = 0.75 + (this.options.random ?? Math.random)() * 0.5
    const delay = Math.min(ceiling, Math.round(base * 2 ** this.attempts * jitter))
    this.attempts += 1
    this.status('backoff', delay)
    this.timer = setTimeout(() => { this.timer = undefined; this.connect() }, delay)
  }

  private stopWithoutStatus() {
    this.unregister?.(); this.unregister = undefined
    this.stopped = true
    if (typeof window !== 'undefined') {
      window.removeEventListener('online', this.onlineListener)
      window.removeEventListener('offline', this.offlineListener)
    }
    subscriptionRegistry.delete(this)
  }

  private status(value: SocketStatus, retryMs?: number) { this.options.onStatus?.(value, retryMs) }
}
