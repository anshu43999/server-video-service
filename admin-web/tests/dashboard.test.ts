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
import { dashboardReads } from '../src/api/readCache'
import { projectScope } from '../src/api/projectScope'
import { useSessionStore } from '../src/stores/session'
import { streamsApi } from '../src/features/streams/api'
import { alertsApi } from '../src/features/alerts/api'
afterEach(() => { dashboardReads.invalidate();projectScope.clear();projectScope.enabled=false;vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
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
it('shares fresh dashboard sources across layouts and fetches only statistics on range change',async()=>{
  vi.useFakeTimers();setActivePinia(createPinia());const projects=useProjectsStore();projects.phase='ready';projects.current=fixtureProject as any
  const stats=vi.spyOn(dashboardApi,'stats').mockImplementation(async range=>statsFixture(range))
  const streams=vi.spyOn(streamsApi,'list').mockResolvedValue([]),events=vi.spyOn(alertsApi,'recent').mockResolvedValue({events:[]})
  function view(){const range=ref<StatsRange>('today');let state!:ReturnType<typeof useDashboard>;const wrapper=mount(defineComponent({setup(){state=useDashboard(range);return()=>null}}));return{wrapper,state,range}}
  const first=view();await flushPromises();first.wrapper.unmount()
  const second=view();await flushPromises();expect(stats).toHaveBeenCalledOnce();expect(streams).toHaveBeenCalledOnce();expect(events).toHaveBeenCalledOnce()
  second.range.value='7d';await flushPromises();expect(stats).toHaveBeenCalledTimes(2);expect(streams).toHaveBeenCalledOnce();expect(events).toHaveBeenCalledOnce()
  second.range.value='today';await flushPromises();expect(stats).toHaveBeenCalledTimes(2)
  await second.state.refresh();expect(stats).toHaveBeenCalledTimes(3);expect(streams).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(10000);await flushPromises();expect(stats).toHaveBeenCalledTimes(4);expect(events).toHaveBeenCalledTimes(3)
  second.wrapper.unmount()
})
it('layout reuse does not extend source freshness beyond its original ten-second deadline',async()=>{
  vi.useFakeTimers();setActivePinia(createPinia());const projects=useProjectsStore();projects.phase='ready';projects.current=fixtureProject as any
  const stats=vi.spyOn(dashboardApi,'stats').mockImplementation(async range=>statsFixture(range))
  const streams=vi.spyOn(streamsApi,'list').mockResolvedValue([]);vi.spyOn(alertsApi,'recent').mockResolvedValue({events:[]})
  const view=()=>mount(defineComponent({setup(){useDashboard(ref<StatsRange>('today'));return()=>null}}))
  const first=view();await flushPromises();await vi.advanceTimersByTimeAsync(9000);first.unmount()
  const second=view();await flushPromises();expect(stats).toHaveBeenCalledOnce()
  await vi.advanceTimersByTimeAsync(1000);await flushPromises()
  expect(stats).toHaveBeenCalledTimes(2);expect(streams).toHaveBeenCalledTimes(2);second.unmount()
})
it('cache invalidation aborts an obsolete read without displaying a business failure',async()=>{
  setActivePinia(createPinia());const projects=useProjectsStore();projects.phase='ready';projects.current=fixtureProject as any
  vi.spyOn(dashboardApi,'stats').mockImplementation(()=>new Promise(()=>{}))
  vi.spyOn(streamsApi,'list').mockResolvedValue([]);vi.spyOn(alertsApi,'recent').mockResolvedValue({events:[]})
  let state!:ReturnType<typeof useDashboard>
  const wrapper=mount(defineComponent({setup(){state=useDashboard(ref<StatsRange>('today'));return()=>null}}))
  await flushPromises();dashboardReads.invalidate(['stats']);await flushPromises()
  expect(state.statsError.value).toBe('');expect(state.loading.value).toBe(false);wrapper.unmount()
})
it('keys cache by actual account and permission revision, then clears all values on scope loss',async()=>{
  setActivePinia(createPinia());projectScope.enable();projectScope.enter('a')
  const projects=useProjectsStore(),session=useSessionStore();projects.phase='ready';projects.current=fixtureProject as any
  session.user={accountId:'alice',username:'alice',role:'admin',platformRole:'PLATFORM_ADMIN'} as any
  const stats=vi.spyOn(dashboardApi,'stats').mockImplementation(async range=>statsFixture(range))
  vi.spyOn(streamsApi,'list').mockResolvedValue([]);vi.spyOn(alertsApi,'recent').mockResolvedValue({events:[]})
  function view(){let state!:ReturnType<typeof useDashboard>;const wrapper=mount(defineComponent({setup(){state=useDashboard(ref<StatsRange>('today'));return()=>null}}));return{wrapper,state}}
  let current=view();await flushPromises();current.wrapper.unmount()
  session.user={...session.user!,accountId:'bob'};current=view();await flushPromises();current.wrapper.unmount()
  projects.current={...projects.current!,membershipRevision:2};current=view();await flushPromises();expect(stats).toHaveBeenCalledTimes(3)
  projectScope.clear();expect(current.state.stats.value).toBeNull();expect(current.state.events.value).toBeNull();expect(current.state.streams.value).toBeNull();current.wrapper.unmount()
})
