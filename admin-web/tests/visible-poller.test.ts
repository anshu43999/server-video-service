// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { VisiblePoller } from '../src/api/visiblePoller'
import { ApiError } from '../src/api/errors'
import { projectScope } from '../src/api/projectScope'

const pollers: VisiblePoller<unknown>[] = []
function visibility(value: DocumentVisibilityState) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value })
  document.dispatchEvent(new Event('visibilitychange'))
}
function online(value: boolean) {
  Object.defineProperty(navigator, 'onLine', { configurable: true, value })
  window.dispatchEvent(new Event(value ? 'online' : 'offline'))
}
function setup(read = vi.fn<(signal: AbortSignal) => Promise<boolean>>().mockResolvedValue(false)) {
  const accept = vi.fn(), error = vi.fn()
  const poller = new VisiblePoller({ read, accept, error, delay: active => active ? 3000 : 30000 })
  pollers.push(poller as VisiblePoller<unknown>)
  return { poller, read, accept, error }
}
beforeEach(() => { vi.useFakeTimers(); visibility('visible'); online(true); projectScope.enable() })
afterEach(() => { pollers.splice(0).forEach(p => p.stop()); projectScope.clear(); projectScope.enabled = false; vi.useRealTimers(); vi.restoreAllMocks() })

describe('visible read polling', () => {
  it('polls idle at 30s, active at 3s and immediately returns to idle after completion', async () => {
    const { poller, read } = setup(); poller.start(); await poller.refresh()
    await vi.advanceTimersByTimeAsync(29999); expect(read).toHaveBeenCalledOnce()
    read.mockResolvedValueOnce(true)
    await vi.advanceTimersByTimeAsync(1); expect(read).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(3000); expect(read).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(29999); expect(read).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1); expect(read).toHaveBeenCalledTimes(4)
  })
  it('backs off 5/10/20/30s, caps retries and resets after success', async () => {
    const { poller, read, error } = setup(); read.mockRejectedValue(new ApiError({ status: 503 }))
    poller.start(); await poller.refresh()
    for (const [i, ms] of [5000, 10000, 20000, 30000, 30000].entries()) {
      await vi.advanceTimersByTimeAsync(ms - 1); expect(read).toHaveBeenCalledTimes(i + 1)
      await vi.advanceTimersByTimeAsync(1); expect(read).toHaveBeenCalledTimes(i + 2)
    }
    expect(error).toHaveBeenCalledTimes(6)
    read.mockResolvedValueOnce(false); await poller.refresh()
    await vi.advanceTimersByTimeAsync(30000)
    const count = read.mock.calls.length
    await vi.advanceTimersByTimeAsync(5000); expect(read).toHaveBeenCalledTimes(count + 1)
  })
  it.each([401, 403, 404, 422])('does not automatically retry terminal HTTP %s', async status => {
    const { poller, read, error } = setup(); read.mockRejectedValue(new ApiError({ status }))
    poller.start(); await poller.refresh(); await vi.advanceTimersByTimeAsync(120000)
    expect(read).toHaveBeenCalledOnce(); expect(error).toHaveBeenCalledOnce()
  })
  it('honors Retry-After and does not treat cancellation as an error', async () => {
    const { poller, read, error } = setup(); read.mockRejectedValueOnce(new ApiError({ status: 429, retryAfterSeconds: 40 }))
    poller.start(); await poller.refresh(); await vi.advanceTimersByTimeAsync(39999)
    expect(read).toHaveBeenCalledOnce(); await vi.advanceTimersByTimeAsync(1); expect(read).toHaveBeenCalledTimes(2)
    error.mockClear(); read.mockRejectedValueOnce(new ApiError({ kind: 'cancelled' })); await poller.refresh()
    await vi.advanceTimersByTimeAsync(60000); expect(read).toHaveBeenCalledTimes(3); expect(error).not.toHaveBeenCalled()
  })
  it('keeps one flight during manual overlap and hidden/resume even if abort is ignored', async () => {
    let finish!: (value: boolean) => void, signal!: AbortSignal
    const { poller, read, accept, error } = setup()
    read.mockImplementationOnce(s => { signal = s; return new Promise(resolve => { finish = resolve }) })
    poller.start(); const pending = poller.refresh(); expect(poller.refresh()).toBe(pending)
    visibility('hidden'); expect(signal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(60000); expect(read).toHaveBeenCalledOnce()
    visibility('visible'); online(true); expect(read).toHaveBeenCalledOnce()
    finish(true); await pending
    expect(read).toHaveBeenCalledTimes(2); expect(accept.mock.calls).toEqual([[false]]); expect(error).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(29999); expect(read).toHaveBeenCalledTimes(2)
  })
  it('pauses for writes without executing or replaying them and refreshes once after resume', async () => {
    const { poller, read } = setup(); poller.start(); await poller.refresh(); poller.pause()
    await vi.advanceTimersByTimeAsync(60000); await poller.refresh(); expect(read).toHaveBeenCalledOnce()
    await poller.resume(); expect(read).toHaveBeenCalledTimes(2)
  })
  it('does not start hidden/offline and coalesces visibility/online recovery', async () => {
    visibility('hidden'); online(false)
    const { poller, read } = setup(); poller.start(); expect(read).not.toHaveBeenCalled()
    visibility('visible'); expect(read).not.toHaveBeenCalled()
    online(true); visibility('visible'); await poller.refresh(); expect(read).toHaveBeenCalledOnce()
    online(false); await vi.advanceTimersByTimeAsync(90000); expect(read).toHaveBeenCalledOnce()
    online(true); await poller.refresh(); expect(read).toHaveBeenCalledTimes(2)
  })
  it.each(['stop', 'scope'] as const)('rejects late results and removes timers/listeners on %s', async action => {
    const { poller, read, accept } = setup(); let finish!: (value: boolean) => void, signal!: AbortSignal
    read.mockImplementationOnce(s => { signal = s; return new Promise(resolve => { finish = resolve }) })
    poller.start(); const pending = poller.refresh()
    action === 'stop' ? poller.stop() : projectScope.clear()
    expect(signal.aborted).toBe(true); finish(true); await pending
    visibility('hidden'); visibility('visible'); online(true); await vi.advanceTimersByTimeAsync(90000)
    expect(read).toHaveBeenCalledOnce(); expect(accept).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0)
  })
})
