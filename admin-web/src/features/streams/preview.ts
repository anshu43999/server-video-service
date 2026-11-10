import { projectScope } from '../../api/projectScope'

export type PreviewStatus = 'idle' | 'paused' | 'connecting' | 'open' | 'waiting' | 'error'
interface PreviewOptions {
  onFrame: (url: string) => void
  onStatus?: (status: PreviewStatus, error?: string) => void
  onMode?: (mode: 'raw' | 'yolo') => void
  fetchImpl?: typeof fetch
  createObjectURL?: (blob: Blob) => string
  revokeObjectURL?: (url: string) => void
  waitForFrameLoad?: boolean
}

/** PC-only snapshots: <=5fps, one unsettled fetch, visible + online only. */
export class AdminPreview {
  private controller?: AbortController
  private timer?: ReturnType<typeof setTimeout>
  private decodeTimer?: ReturnType<typeof setTimeout>
  private flight?: Promise<void>
  private objectUrl = ''
  private previousUrl = ''
  private waitingForFrame = false
  private generation = 0
  private unregister?: () => void
  private path = ''
  private visible = true
  private suspended = true
  private failures = 0

  constructor(private readonly options: PreviewOptions) {}
  private eligible() {
    return !!this.path && this.visible && (typeof document === 'undefined' || document.visibilityState !== 'hidden') &&
      (typeof navigator === 'undefined' || navigator.onLine !== false)
  }
  private environment = () => {
    if (!this.eligible()) { this.pause(); return }
    if (!this.suspended) return
    this.suspended = false; this.failures = 0; this.options.onStatus?.('connecting'); this.request()
  }
  setVisible(visible: boolean) {
    if (this.visible === visible) return
    this.visible = visible
    if (this.path) this.environment()
  }
  private cancelTimer() { if (this.timer !== undefined) clearTimeout(this.timer); this.timer = undefined }
  private pause() {
    this.suspended = true
    this.generation++; this.cancelTimer(); this.controller?.abort(); this.clearFrame()
    this.options.onStatus?.('paused')
  }
  private schedule(delay: number) {
    this.cancelTimer()
    if (this.eligible()) this.timer = setTimeout(() => { this.timer = undefined; this.request() }, delay)
  }
  private backoff() { return [500, 1000, 2000, 5000][Math.min(this.failures++, 3)]! }
  private request() {
    if (!this.eligible() || this.flight || this.waitingForFrame) return
    this.cancelTimer()
    const generation = this.generation
    const flight = this.read(this.path, generation).finally(() => {
      if (this.flight !== flight) return
      this.flight = undefined
      // Resume only after an interrupted transport settles, even if it ignores abort.
      if (this.eligible() && generation !== this.generation) this.request()
    })
    this.flight = flight
  }
  start(path: string) {
    if (!/^\/aiyoloapi\/streams\/[^/?#]+\/preview\?connection=\d+$/.test(path)) {
      throw new TypeError('Admin preview must use the same-origin stream API')
    }
    this.stop()
    this.path = projectScope.path(path); this.failures = 0
    this.unregister = projectScope.enabled ? projectScope.register(() => this.stop()) : undefined
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', this.environment)
    if (typeof window !== 'undefined') { window.addEventListener('online', this.environment); window.addEventListener('offline', this.environment) }
    this.environment()
  }
  stop() {
    this.path = ''
    this.suspended = true
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', this.environment)
    if (typeof window !== 'undefined') { window.removeEventListener('online', this.environment); window.removeEventListener('offline', this.environment) }
    this.unregister?.(); this.unregister = undefined
    this.generation++; this.cancelTimer(); this.controller?.abort(); this.clearFrame()
    this.options.onStatus?.('idle')
  }
  frameLoaded() {
    if (!this.waitingForFrame || !this.eligible()) return
    this.waitingForFrame = false; this.failures = 0
    if (this.decodeTimer !== undefined) clearTimeout(this.decodeTimer)
    this.decodeTimer = undefined
    if (this.previousUrl) { this.revoke(this.previousUrl); this.previousUrl = '' }
    this.options.onStatus?.('open'); this.schedule(200)
  }
  frameFailed() {
    if (!this.eligible()) return
    this.clearFrame(); this.options.onStatus?.('error', 'Preview image unavailable'); this.schedule(this.backoff())
  }
  private async read(path: string, generation: number) {
    const controller = new AbortController()
    this.controller = controller
    let delay = 200, timedOut = false
    const timeout = setTimeout(() => {
      timedOut = true
      if (generation === this.generation) delay = this.backoff()
      controller.abort()
      if (generation === this.generation) { this.clearFrame(); this.options.onStatus?.('error', 'Preview timeout') }
    }, 5000)
    try {
      const response = await (this.options.fetchImpl ?? globalThis.fetch)(path, {
        signal: controller.signal, credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'image/jpeg' },
      })
      if (generation !== this.generation || controller.signal.aborted) return
      if ([401, 403, 404].includes(response.status)) {
        this.stop(); this.options.onStatus?.('error', 'HTTP ' + response.status); projectScope.onDenied?.(); return
      }
      if (response.status === 204) {
        this.clearFrame(); this.options.onStatus?.('waiting'); delay = this.backoff()
      } else {
        if (!response.ok || !response.headers.get('content-type')?.startsWith('image/jpeg')) throw new Error('Preview unavailable')
        const blob = await response.blob()
        if (generation !== this.generation || controller.signal.aborted) return
        if (blob.size < 1 || blob.size > 20 * 1024 * 1024) throw new Error('Invalid preview size')
        this.publish(blob)
        this.options.onMode?.(response.headers.get('x-preview-mode') === 'yolo' ? 'yolo' : 'raw')
        if (!this.options.waitForFrameLoad) { this.failures = 0; this.options.onStatus?.('open') }
      }
    } catch (error) {
      if (generation !== this.generation) return
      this.clearFrame(); this.options.onStatus?.('error', error instanceof Error ? error.message : 'Preview unavailable')
      if (!timedOut) delay = this.backoff()
    } finally {
      clearTimeout(timeout)
      if (this.controller === controller) this.controller = undefined
      if (generation === this.generation && !this.waitingForFrame) this.schedule(delay)
    }
  }
  private publish(blob: Blob) {
    const next = (this.options.createObjectURL ?? URL.createObjectURL.bind(URL))(blob)
    if (this.options.waitForFrameLoad) {
      this.previousUrl = this.objectUrl; this.waitingForFrame = true
      this.decodeTimer = setTimeout(() => this.frameFailed(), 5000)
      this.options.onStatus?.('connecting')
    } else if (this.objectUrl) this.revoke(this.objectUrl)
    this.objectUrl = next; this.options.onFrame(next)
  }
  private revoke(url: string) { (this.options.revokeObjectURL ?? URL.revokeObjectURL.bind(URL))(url) }
  private clearFrame() {
    this.waitingForFrame = false
    if (this.decodeTimer !== undefined) clearTimeout(this.decodeTimer)
    this.decodeTimer = undefined
    if (this.previousUrl) { this.revoke(this.previousUrl); this.previousUrl = '' }
    if (this.objectUrl) { this.revoke(this.objectUrl); this.objectUrl = ''; this.options.onFrame('') }
    this.options.onMode?.('raw')
  }
}
