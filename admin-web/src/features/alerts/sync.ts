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
  private timer?: ReturnType<typeof setInterval>
  private socket?: Socket
  private release?: () => void

  constructor(private readonly store: AlertSyncStore,
    private readonly createSocket: (options: ManagedSocketOptions<unknown>) => Socket = (options) => new ManagedWebSocket(options),
    private readonly pollMs = 5000) {}

  async start() {
    this.stop()
    const generation = this.generation
    this.release = projectScope.register(() => this.stop())
    await this.store.refresh({ background: true })
    if (generation !== this.generation) return
    this.socket = this.createSocket({
      path: '/aiyoloapi/alerts/ws',
      onMessage: (message) => { if (generation === this.generation) this.store.acceptRealtime(message) },
      onStatus: (status) => {
        if (generation !== this.generation) return
        this.store.socketStatus = status
        // Catch alerts missed before the handshake or while offline.
        if (status === 'open') void this.store.refresh({ background: true })
      },
      onTerminal: () => this.stop(),
    })
    this.socket.start()
    if (generation === this.generation) {
      this.timer = setInterval(() => { void this.store.refresh({ background: true }) }, this.pollMs)
    }
  }

  stop() {
    this.generation++
    this.release?.(); this.release = undefined
    if (this.timer !== undefined) clearInterval(this.timer)
    this.timer = undefined
    this.socket?.stop(); this.socket = undefined
  }
}
