import { projectScope } from '../../api/projectScope'

export type PreviewStatus = 'idle' | 'connecting' | 'open' | 'waiting' | 'error'
interface PreviewOptions {
  onFrame: (url: string) => void
  onStatus?: (status: PreviewStatus, error?: string) => void
  onMode?: (mode: 'raw' | 'yolo') => void
  fetchImpl?: typeof fetch
  createObjectURL?: (blob: Blob) => string
  revokeObjectURL?: (url: string) => void
  waitForFrameLoad?: boolean
}

/** PC-only, same-origin snapshot polling. No mobile playback or detection WS. */
export class AdminPreview {
  private controller?: AbortController
  private timer?: ReturnType<typeof setTimeout>
  private objectUrl = ''
  private previousUrl = ''
  private waitingForFrame = false
  private generation = 0
  private unregister?: () => void

  constructor(private readonly options: PreviewOptions) {}

  start(path: string) {
    if (!/^\/aiyoloapi\/streams\/[^/?#]+\/preview\?connection=\d+$/.test(path)) {
      throw new TypeError('Admin preview must use the same-origin stream API')
    }
    this.stop()
    path = projectScope.path(path)
    this.unregister = projectScope.enabled ? projectScope.register(() => this.stop()) : undefined
    const generation = ++this.generation
    this.options.onStatus?.('connecting')
    void this.read(path, generation)
  }

  stop() {
    this.unregister?.(); this.unregister = undefined
    this.generation += 1
    if (this.timer) clearTimeout(this.timer)
    this.timer = undefined
    this.controller?.abort()
    this.controller = undefined
    this.clearFrame()
    this.options.onStatus?.('idle')
  }

  frameLoaded() {
    this.waitingForFrame = false
    if (this.previousUrl) { this.revoke(this.previousUrl); this.previousUrl = '' }
  }

  private async read(path: string, generation: number) {
    if (generation !== this.generation) return
    const controller = new AbortController()
    this.controller = controller
    // A stalled request must clear the old picture, not imply a live feed.
    const timeout = setTimeout(() => controller.abort(), 5000)
    let retry = true
    try {
      const response = await (this.options.fetchImpl ?? globalThis.fetch)(path, {
        signal: controller.signal, credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'image/jpeg' },
      })
      if (generation !== this.generation || controller.signal.aborted) return
      if ([401, 403, 404].includes(response.status)) {
        retry = false
        this.clearFrame()
        this.options.onStatus?.('error', `HTTP ${response.status}`)
        projectScope.onDenied?.()
        return
      }
      if (response.status === 204) {
        this.clearFrame()
        this.options.onStatus?.('waiting')
      } else {
        if (!response.ok || !response.headers.get('content-type')?.startsWith('image/jpeg')) throw new Error('Preview unavailable')
        const blob = await response.blob()
        if (generation !== this.generation || controller.signal.aborted) return
        if (blob.size < 1 || blob.size > 20 * 1024 * 1024) throw new Error('Invalid preview size')
        if (this.publish(blob)) this.options.onMode?.(response.headers.get('x-preview-mode') === 'yolo' ? 'yolo' : 'raw')
        this.options.onStatus?.('open')
      }
    } catch (error) {
      if (generation !== this.generation) return
      this.clearFrame()
      this.options.onStatus?.('error', error instanceof Error ? error.message : 'Preview unavailable')
    } finally {
      clearTimeout(timeout)
      if (this.controller === controller) this.controller = undefined
      if (retry && generation === this.generation) this.timer = setTimeout(() => { void this.read(path, generation) }, 200)
    }
  }

  private publish(blob: Blob) {
    if (this.waitingForFrame) return false
    const next = (this.options.createObjectURL ?? URL.createObjectURL.bind(URL))(blob)
    if (this.options.waitForFrameLoad) { this.previousUrl = this.objectUrl; this.waitingForFrame = true }
    else if (this.objectUrl) this.revoke(this.objectUrl)
    this.objectUrl = next
    this.options.onFrame(next)
    return true
  }

  private revoke(url: string) { (this.options.revokeObjectURL ?? URL.revokeObjectURL.bind(URL))(url) }

  private clearFrame() {
    this.frameLoaded()
    if (this.objectUrl) { this.revoke(this.objectUrl); this.objectUrl = ''; this.options.onFrame('') }
    this.options.onMode?.('raw')
  }
}
