import { projectScope } from './projectScope'

interface Entry {
  tag: string
  controller: AbortController
  promise: Promise<unknown>
  users: number
  expires: number
  ready: boolean
  value?: unknown
}

/** Small, tab-memory-only read pilot. Never caches writes or authorization. */
export class ReadCache {
  private entries = new Map<string, Entry>()
  constructor(private readonly ttlMs = 10_000, private readonly maxEntries = 32) {}
  remaining(context: string, tag: string, parameters: string): number | undefined {
    const entry = this.entries.get(JSON.stringify([context, tag, parameters]))
    return entry?.ready ? Math.max(0, entry.expires - Date.now()) : undefined
  }
  invalidate(tags?: string[]) {
    for (const [key, entry] of this.entries) {
      if (!tags || tags.includes(entry.tag)) { this.entries.delete(key); entry.controller.abort() }
    }
  }
  read<T>(context: string, tag: string, parameters: string, load: (signal: AbortSignal) => Promise<T>, signal: AbortSignal): Promise<T> {
    if (signal.aborted) return Promise.reject(projectScope.cancelled())
    const key = JSON.stringify([context, tag, parameters])
    let entry = this.entries.get(key)
    if (entry?.ready && entry.expires > Date.now()) {
      const cached = entry
      return Promise.resolve().then(() => {
        if (signal.aborted || cached.controller.signal.aborted || this.entries.get(key) !== cached) throw projectScope.cancelled()
        return structuredClone(cached.value) as T
      })
    }
    if (entry?.ready) { this.entries.delete(key); entry = undefined }
    if (!entry) {
      for (const [oldKey, old] of this.entries) {
        if (old.ready && (old.expires <= Date.now() || this.entries.size >= this.maxEntries)) this.entries.delete(oldKey)
      }
      const controller = new AbortController()
      const created: Entry = { tag, controller, promise: Promise.resolve(), users: 0, expires: 0, ready: false }
      this.entries.set(key, created)
      created.promise = Promise.resolve().then(() => {
        if (controller.signal.aborted) throw projectScope.cancelled()
        return load(controller.signal)
      }).then(value => {
        if (controller.signal.aborted || this.entries.get(key) !== created) throw projectScope.cancelled()
        created.value = structuredClone(value); created.ready = true; created.expires = Date.now() + this.ttlMs
        for (const [oldKey, old] of this.entries) {
          if (this.entries.size <= this.maxEntries) break
          if (old.ready && old !== created) this.entries.delete(oldKey)
        }
        return value
      }).catch(reason => {
        if (this.entries.get(key) === created) this.entries.delete(key)
        throw reason
      })
      entry = created
    }
    const active = entry
    active.users++
    return new Promise<T>((resolve, reject) => {
      let done = false
      const finish = () => {
        if (done) return false
        done = true; signal.removeEventListener('abort', abort); active.controller.signal.removeEventListener('abort', invalidate)
        active.users--; return true
      }
      const abort = () => {
        if (!finish()) return
        reject(projectScope.cancelled())
        if (!active.ready && active.users === 0) {
          if (this.entries.get(key) === active) this.entries.delete(key)
          active.controller.abort()
        }
      }
      const invalidate = () => { if (finish()) reject(projectScope.cancelled()) }
      signal.addEventListener('abort', abort, { once: true })
      active.controller.signal.addEventListener('abort', invalidate, { once: true })
      active.promise.then(value => { if (finish()) resolve(structuredClone(value) as T) }, reason => { if (finish()) reject(reason) })
    })
  }
}

export const dashboardReads = new ReadCache()
export const managementReads = new ReadCache()
projectScope.onClear(() => { dashboardReads.invalidate(); managementReads.invalidate() })

// Account or membership changes can affect both member names and project owners.
// These are display snapshots only, never permission or mutation-result caches.
export function invalidateManagementWrite(path: string) {
  path = path.split('?')[0]!
  if (new RegExp('^/aiyoloapi/platform/(accounts|projects)(?:/|$)').test(path) ||
      new RegExp('^/aiyoloapi/projects/[^/]+/(members|transfer-owner)(?:/|$)').test(path)) managementReads.invalidate()
}

// Invalidate before and after a write, including uncertain outcomes. No replay.
export function invalidateDashboardWrite(path: string) {
  path = path.split('?')[0]!
  if (/\/(alerts|alert-advice)(?:\/|$)/.test(path)) dashboardReads.invalidate(['stats', 'recent'])
  if (/\/(streams|models|model-assignments|scenes|rules)(?:\/|$)/.test(path)) dashboardReads.invalidate(['stats', 'streams'])
}
