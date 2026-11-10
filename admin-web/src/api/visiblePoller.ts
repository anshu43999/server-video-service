import { ApiError } from './errors'
import { projectScope } from './projectScope'

interface PollOptions<T> {
  read: (signal: AbortSignal) => Promise<T>
  accept: (value: T) => void
  error: (reason: unknown) => void
  delay: (value: T) => number
  enabled?: () => boolean
}

/** GET-only callers: one unsettled read, even if a transport ignores abort.
 * Hidden/offline/write pauses cancel the old read; resume coalesces one fresh
 * read after it settles. Never retain a timer or response across scope reset. */
export class VisiblePoller<T> {
  private timer?: ReturnType<typeof setTimeout>
  private controller?: AbortController
  private flight?: Promise<void>
  private release?: () => void
  private started = false
  private stopped = false
  private paused = false
  private rerun = false
  private failures = 0
  private nextDelay?: number

  constructor(private readonly options: PollOptions<T>) {}

  private eligible() {
    return this.started && !this.stopped && !this.paused && document.visibilityState !== 'hidden' &&
      navigator.onLine !== false && (this.options.enabled?.() ?? true)
  }
  private clearTimer() {
    if (this.timer !== undefined) clearTimeout(this.timer)
    this.timer = undefined
  }
  private interrupt() { this.clearTimer(); this.rerun = false; this.controller?.abort() }
  private visibility = () => {
    if (this.eligible()) void this.refresh()
    else this.interrupt()
  }

  start() {
    if (this.started || this.stopped) return
    this.started = true
    document.addEventListener('visibilitychange', this.visibility)
    window.addEventListener('online', this.visibility)
    window.addEventListener('offline', this.visibility)
    if (projectScope.enabled) this.release = projectScope.register(() => this.stop())
    void this.refresh()
  }
  pause() { this.paused = true; this.interrupt() }
  resume() { this.paused = false; return this.refresh() }
  stop() {
    this.stopped = true; this.interrupt()
    this.release?.(); this.release = undefined
    document.removeEventListener('visibilitychange', this.visibility)
    window.removeEventListener('online', this.visibility)
    window.removeEventListener('offline', this.visibility)
  }

  refresh(): Promise<void> {
    if (!this.eligible()) return Promise.resolve()
    this.clearTimer()
    if (this.flight) {
      if (this.controller?.signal.aborted) this.rerun = true
      return this.flight
    }
    const pending = this.read().finally(() => {
      if (this.flight !== pending) return
      this.flight = undefined
      if (this.eligible() && this.nextDelay !== undefined) {
        this.timer = setTimeout(() => { void this.refresh() }, this.nextDelay)
      }
    })
    this.flight = pending
    return pending
  }

  private async read() {
    do {
      this.rerun = false; this.nextDelay = undefined
      const controller = new AbortController(), generation = projectScope.generation
      this.controller = controller
      try {
        const value = await this.options.read(controller.signal)
        if (!this.eligible() || controller.signal.aborted || generation !== projectScope.generation) continue
        this.failures = 0
        this.options.accept(value)
        this.nextDelay = this.options.delay(value)
      } catch (error) {
        if (!this.eligible() || controller.signal.aborted || generation !== projectScope.generation) continue
        if (error instanceof ApiError && error.kind === 'cancelled') continue
        this.options.error(error)
        const transient = !(error instanceof ApiError) || ['network', 'timeout'].includes(error.kind) ||
          error.status === 408 || error.status === 429 || (error.status ?? 0) >= 500
        if (transient) {
          const delays = [5000, 10000, 20000, 30000]
          this.nextDelay = delays[Math.min(this.failures++, delays.length - 1)]
          if (error instanceof ApiError && error.retryAfterSeconds) this.nextDelay = Math.max(this.nextDelay, error.retryAfterSeconds * 1000)
        }
      } finally {
        if (this.controller === controller) this.controller = undefined
      }
    } while (this.rerun && this.eligible())
  }
}
