import { describe, expect, it } from 'vitest'
import { createCatalogChangeTracker } from '../src/features/models/catalogChanges'
import type { ConversionJob } from '../src/features/models/types'
const job = (overrides: Partial<ConversionJob> = {}): ConversionJob => ({ id: 'one', action: 'inspect', status: 'running', attempt: 1, created_at: 1, metadata: {}, ...overrides })
describe('catalog refresh semantics', () => {
  it('does not refresh for initial history, progress, logs, or check jobs', () => {
    const changed = createCatalogChangeTracker()
    expect(changed([job({ status: 'succeeded' }), job({ id: 'active' })])).toBe(false)
    expect(changed([job({ status: 'succeeded', result: { message: 'log changed' } }), job({ id: 'active', progress: 60, stage_label: 'working' })])).toBe(false)
    expect(changed([job({ action: 'check', id: 'check', status: 'succeeded' })])).toBe(false)
  })
  it.each(['succeeded', 'failed', 'interrupted'] as const)('refreshes a model-affecting terminal attempt once: %s', status => {
    const changed = createCatalogChangeTracker()
    changed([job()]); expect(changed([job({ status })])).toBe(true)
    expect(changed([job({ status, error: 'late detail', completed_at: 3 })])).toBe(false)
    changed([]); expect(changed([job({ status })])).toBe(false)
    changed([job({ attempt: 2 })]); expect(changed([job({ status, attempt: 2 })])).toBe(true)
  })
  it('coalesces multiple finished jobs and catches fast jobs between polls', () => {
    const changed = createCatalogChangeTracker()
    changed([])
    expect(changed([job({ status: 'succeeded' }), job({ id: 'two', action: 'mobile', status: 'failed' })])).toBe(true)
    expect(changed([job({ status: 'succeeded' }), job({ id: 'two', action: 'mobile', status: 'failed' })])).toBe(false)
  })
})
