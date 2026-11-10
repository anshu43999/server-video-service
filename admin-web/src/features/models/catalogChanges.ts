import type { ConversionJob } from './types'

/** Job progress/logs are not catalog changes. A terminal inspect/mobile attempt
 * may have registered or partially changed an artifact, including on failure.
 * Refresh authoritative metadata once; never infer model readiness from a job. */
export function createCatalogChangeTracker() {
  let initialized = false
  const terminalAttempts = new Set<string>()
  return (jobs: ConversionJob[]) => {
    let changed = false
    for (const job of jobs) {
      if (job.action === 'check' || !['succeeded', 'failed', 'interrupted'].includes(job.status)) continue
      const key = JSON.stringify([job.id, job.attempt])
      if (!terminalAttempts.has(key)) {
        terminalAttempts.add(key)
        if (initialized) changed = true
      }
    }
    initialized = true
    return changed
  }
}
