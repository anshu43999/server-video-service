import { projectScope } from '../../api/projectScope'

interface Job { cancel: () => void; start: () => void; signal: AbortSignal }
/** Tab-local concurrency budget shared by thumbnails and detail/original reads.
 * Cancelled transports retain their slot until settled; no unbounded overlap. */
export class EvidenceRequests {
  private active = 0
  private queued: Job[] = []
  private jobs = new Set<Job>()
  constructor(private readonly limit = 3) {}
  clear() { for (const job of [...this.jobs]) job.cancel() }
  run<T>(load: (signal: AbortSignal) => Promise<T>, caller: AbortSignal): Promise<T> {
    if (caller.aborted) return Promise.reject(projectScope.cancelled())
    return new Promise<T>((resolve, reject) => {
      const controller = new AbortController(), generation = projectScope.generation
      let started = false, settled = false
      const finish = () => { caller.removeEventListener('abort', job.cancel); this.jobs.delete(job) }
      const job: Job = {
        signal: controller.signal,
        cancel: () => {
          if (settled) return
          settled = true; controller.abort(); reject(projectScope.cancelled()); finish()
          if (!started) this.queued = this.queued.filter(item => item !== job)
        },
        start: () => {
          started = true; this.active++
          Promise.resolve().then(() => {
            if (controller.signal.aborted) throw projectScope.cancelled()
            return load(controller.signal)
          }).then(value => {
            if (settled) return
            settled = true
            if (controller.signal.aborted || generation !== projectScope.generation) reject(projectScope.cancelled())
            else resolve(value)
          }, error => { if (!settled) { settled = true; reject(error) } }).finally(() => {
            finish(); this.active--; this.drain()
          })
        },
      }
      caller.addEventListener('abort', job.cancel, { once: true })
      this.jobs.add(job); this.queued.push(job); this.drain()
    })
  }
  private drain() {
    while (this.active < this.limit && this.queued.length) {
      const job = this.queued.shift()!
      if (!job.signal.aborted) job.start()
    }
  }
}
export const evidenceRequests = new EvidenceRequests()
projectScope.onClear(() => evidenceRequests.clear())
