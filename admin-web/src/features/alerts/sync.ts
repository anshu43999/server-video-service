import { ManagedWebSocket, type ManagedSocketOptions, type SocketStatus } from '../../api/realtime'
import { projectScope } from '../../api/projectScope'

interface AlertSyncStore {
  refresh: (options?: { background?: boolean }) => Promise<void>
  acceptRealtime: (message: unknown) => boolean
  socketStatus: SocketStatus
}
type Socket = Pick<ManagedWebSocket, 'start' | 'stop'>

/** REST is the durable source of truth; WS only accelerates already stored alerts. */
export class AlertSync {
  private generation = 0
  private timer?: ReturnType<typeof setTimeout>
  private socket?: Socket
  private release?: () => void
  private refreshing?: Promise<void>
  private reconcileAgain = false

  constructor(private readonly store: AlertSyncStore,
    private readonly createSocket: (options: ManagedSocketOptions<unknown>) => Socket = (options) => new ManagedWebSocket(options),
    private readonly pollMs = 5000) {}

  async start() {
    this.stop()
    const generation = this.generation
    this.release = projectScope.register(() => this.stop())
    await this.reconcile(generation)
    if (generation !== this.generation) return
    let previousStatus: SocketStatus = 'idle'
    this.socket = this.createSocket({
      path: '/aiyoloapi/alerts/ws',
      onMessage: (message) => { if (generation === this.generation) this.store.acceptRealtime(message) },
      onStatus: (status) => {
        if (generation !== this.generation) return
        const previous = previousStatus
        previousStatus = status
        this.store.socketStatus = status
        // Reconcile both loss of a live connection and recovery. A reconnect
        // during a pending list must also read AFTER that snapshot settles.
        if ((status === 'open' && previous !== 'open')
          || (previous === 'open' && ['backoff', 'offline', 'stopped'].includes(status))) {
          void this.reconcile(generation)
        }
      },
      onTerminal: () => { if (generation === this.generation) this.stop() },
    })
    this.socket.start()
  }

  private async reconcile(generation: number): Promise<void> {
    if (generation !== this.generation) return
    if (this.timer !== undefined) clearTimeout(this.timer)
    this.timer = undefined
    if (this.refreshing) {
      this.reconcileAgain = true
      return this.refreshing.catch(() => {})
    }
    this.refreshing = Promise.resolve().then(() => {
      if (generation === this.generation) return this.store.refresh({ background: true })
    })
    try {
      await this.refreshing
    } catch {
      // The store owns the visible error; a failed read must not kill recovery.
    } finally {
      if (generation === this.generation) {
        this.refreshing = undefined
        if (this.reconcileAgain) {
          this.reconcileAgain = false
          void this.reconcile(generation)
        } else {
          // WS is policy-filtered, lossy and lacks all state updates. Keep the
          // 5s REST safety net even when open; 30s requires coverage approval.
          this.timer = setTimeout(() => { void this.reconcile(generation) }, this.pollMs)
        }
      }
    }
  }

  stop() {
    this.generation++
    this.release?.(); this.release = undefined
    if (this.timer !== undefined) clearTimeout(this.timer)
    this.timer = undefined
    this.refreshing = undefined
    this.reconcileAgain = false
    this.socket?.stop(); this.socket = undefined
  }
}
