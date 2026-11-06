// @vitest-environment happy-dom
import { createPinia, setActivePinia } from 'pinia'
import { useProjectsStore } from '../src/stores/projects'
import { fixtureProject } from '../tests-e2e/helpers/project-fixture'
import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { dashboardApi, parseStats } from '../src/features/dashboard/api'
import { canPreview, percent, streamStatus } from '../src/features/dashboard/presenters'
import { useDashboard } from '../src/features/dashboard/useDashboard'
import type { StatsRange } from '../src/features/dashboard/types'
import { statsFixture } from './fixtures/dashboard'
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
it('preserves real zeroes, null resources and rejects wrong ranges or incomplete statistics', async () => {
  expect(parseStats(statsFixture('today', 0), 'today').summary.totalEvents).toBe(0)
  expect(percent(0)).toBe('0.0%'); expect(percent(null)).toBe('不可用')
  expect(parseStats(statsFixture(), 'today').system.gpu).toBe(null)
  expect(() => parseStats({ events: [] }, 'today')).toThrow('统计响应无效')
  expect(() => parseStats(statsFixture('7d'), 'today')).toThrow('统计响应无效')
  const bad = statsFixture(); bad.summary.totalEvents = NaN
  expect(() => parseStats(bad, 'today')).toThrow('统计响应无效')
  const fetch = vi.fn(async (_input: RequestInfo | URL) => new Response(JSON.stringify(statsFixture('30d')))); vi.stubGlobal('fetch', fetch)
  await dashboardApi.stats('30d'); expect(fetch.mock.calls[0]?.[0]).toBe('/aiyoloapi/dashboard/stats?range=30d')
})
it('does not classify stopped or missing runtimes as online from historical frames', () => {
  const stream = { stream_id: 'gate', frames_received: 10000, received_fps: 20, runtime_available: false, enabled: false }
  expect(streamStatus(stream).label).toBe('已停用'); expect(canPreview(stream)).toBe(false)
  expect(streamStatus({ ...stream, enabled: true }).label).toBe('未运行')
  expect(streamStatus({ ...stream, enabled: true, runtime_available: true, received_fps: 0 }).label).toBe('等待画面')
})
it('ignores a late old range, keeps partial sources independent, retries and aborts on disposal', async () => {
  setActivePinia(createPinia()); const projects=useProjectsStore(); projects.phase='ready'; projects.current=fixtureProject as any
  vi.useFakeTimers()
  let release: (value: Response) => void = () => {}
  const signals: AbortSignal[] = [], ranges: string[] = []
  vi.stubGlobal('fetch', vi.fn((input: string, options: RequestInit) => {
    signals.push(options.signal as AbortSignal)
    if (input.includes('/dashboard/stats')) {
      const range = new URL(input, 'http://localhost').searchParams.get('range') as StatsRange
      ranges.push(range)
      if (range === 'today') return new Promise<Response>(resolve => { release = resolve })
      return Promise.resolve(new Response(JSON.stringify(statsFixture(range, 30))))
    }
    if (input.endsWith('/streams')) return Promise.resolve(new Response(JSON.stringify({ detail: '流读取失败' }), { status: 503 }))
    return Promise.resolve(new Response(JSON.stringify({ events: [] })))
  }))
  const range = ref<StatsRange>('today')
  let state!: ReturnType<typeof useDashboard>
  const wrapper = mount(defineComponent({ setup() { state = useDashboard(range); return () => null } }))
  await flushPromises(); range.value = '30d'; await flushPromises()
  expect(signals[0]?.aborted).toBe(true)
  expect(state.stats.value?.summary.totalEvents).toBe(30); expect(state.streams.value).toBe(null); expect(state.streamsError.value).toBeTruthy(); expect(state.events.value).toEqual([])
  release(new Response(JSON.stringify(statsFixture('today', 99)))); await flushPromises()
  expect(state.stats.value?.range).toBe('30d')
  await vi.advanceTimersByTimeAsync(10_000); await flushPromises(); expect(ranges).toEqual(['today', '30d', '30d'])
  wrapper.unmount(); const count = ranges.length
  await vi.advanceTimersByTimeAsync(30_000); expect(ranges).toHaveLength(count)
})
