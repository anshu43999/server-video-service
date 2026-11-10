// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { mount, type VueWrapper } from '@vue/test-utils'
import { useProjectsStore } from '../src/stores/projects'
import { projectScope } from '../src/api/projectScope'
import { ApiError } from '../src/api/errors'
import ConversionPane from '../src/features/models/ConversionPane.vue'
import PushView from '../src/features/operations/PushView.vue'
import { conversionApi } from '../src/features/models/api'
import { operationsApi, type DeliveryStatus } from '../src/features/operations/api'
import type { ConversionJob } from '../src/features/models/types'

let pinia: ReturnType<typeof createPinia>
const wrappers: VueWrapper[] = []
const slot = { template: '<div><slot /></div>' }
const global = { stubs: {
  UiButton: { template: '<button><slot /></button>' }, UiInput: true, UiSelect: slot, UiOption: slot,
  UiStatePanel: true, UiDialog: slot, UiCollapse: slot, UiTag: slot, UiProgress: true, UiConfirmDialog: true,
} }
const job = (status: ConversionJob['status']): ConversionJob => ({ id: 'job', action: 'inspect', status, attempt: 1, created_at: 1, metadata: {} })
const delivery = (pending = 0): DeliveryStatus => ({ channels: { app: { enabled: true, subscribers: 1 } }, pending, recent: [] })
const tick = () => vi.advanceTimersByTimeAsync(0)
function hidden(value: boolean) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: value ? 'hidden' : 'visible' })
  document.dispatchEvent(new Event('visibilitychange'))
}
async function click(wrapper: VueWrapper, name: string) { await wrapper.findAll('button').find(button => button.text() === name)!.trigger('click'); await tick() }
function conversion() { const wrapper = mount(ConversionPane, { props: { families: [] }, global }); wrappers.push(wrapper); return wrapper }
function push() { const wrapper = mount(PushView, { global }); wrappers.push(wrapper); return wrapper }
beforeEach(() => {
  vi.useFakeTimers(); hidden(false)
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
  pinia = createPinia(); setActivePinia(pinia); projectScope.enable(); projectScope.enter('a')
  const projects = useProjectsStore()
  projects.phase = 'ready'
  projects.current = { projectId: 'a', projectCode: 'a', displayName: 'A', lifecycleState: 'ACTIVE', revision: 1, membershipRevision: 1, projectRole: 'PROJECT_OWNER', platformEntry: false, capabilities: ['project.read', 'project.settings.manage'] }
  vi.spyOn(conversionApi, 'config').mockResolvedValue({ config: { mode: 'local', default_calibration_dataset_id: '' }, max_upload_bytes: 1000 } as never)
  vi.spyOn(conversionApi, 'datasets').mockResolvedValue({ datasets: [] } as never)
  vi.spyOn(conversionApi, 'jobs').mockResolvedValue([])
  vi.spyOn(operationsApi, 'policy').mockResolvedValue({ revision: 1, enabled: true, channels: ['app'], minimumSeverity: 'MINOR' })
  vi.spyOn(operationsApi, 'delivery').mockResolvedValue(delivery())
})
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); projectScope.clear(); projectScope.enabled = false; disposePinia(pinia); vi.restoreAllMocks(); vi.useRealTimers() })

describe('conversion read polling', () => {
  it('polls check/inspect active jobs at 3s, finished jobs at 30s and emits one catalog change', async () => {
    vi.mocked(conversionApi.jobs).mockResolvedValue([job('running')])
    const wrapper = conversion(); await tick(); expect(conversionApi.jobs).toHaveBeenCalledOnce()
    await vi.advanceTimersByTimeAsync(3000); expect(conversionApi.jobs).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('changed')).toBeUndefined()
    vi.mocked(conversionApi.jobs).mockResolvedValue([job('succeeded')])
    await vi.advanceTimersByTimeAsync(3000); expect(wrapper.emitted('changed')).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(29999); expect(conversionApi.jobs).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1); expect(conversionApi.jobs).toHaveBeenCalledTimes(4)
    expect(wrapper.emitted('changed')).toHaveLength(1)
    vi.mocked(conversionApi.jobs).mockResolvedValue([{ ...job('running'), action: 'check' }])
    await click(wrapper, '刷新任务'); await vi.advanceTimersByTimeAsync(3000)
    expect(conversionApi.jobs).toHaveBeenCalledTimes(6)
  })
  it('stops hidden and coalesces resume, then applies read-only failure backoff', async () => {
    const wrapper = conversion(); await tick(); hidden(true)
    await vi.advanceTimersByTimeAsync(90000); expect(conversionApi.jobs).toHaveBeenCalledOnce()
    hidden(false); await tick(); expect(conversionApi.jobs).toHaveBeenCalledTimes(2)
    vi.mocked(conversionApi.jobs).mockRejectedValue(new ApiError({ status: 503 }))
    await click(wrapper, '刷新任务')
    for (const ms of [5000, 10000, 20000, 30000]) await vi.advanceTimersByTimeAsync(ms)
    expect(conversionApi.jobs).toHaveBeenCalledTimes(7)
    expect(wrapper.text()).toContain('当前任务状态可能已过期')
    expect(conversionApi.config).toHaveBeenCalledOnce()
  })
  it('never replays failed conversion writes; resumes only GET fact checks', async () => {
    const write = vi.spyOn(conversionApi, 'check').mockRejectedValue(new ApiError({ status: 503 }))
    const wrapper = conversion(); await tick(); await click(wrapper, '检测转换环境')
    expect(write).toHaveBeenCalledOnce(); expect(conversionApi.jobs).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(90000); expect(write).toHaveBeenCalledOnce()
  })
})

describe('push status polling', () => {
  it('retries failed status reads without re-reading policy and drops a late response after scope change', async () => {
    vi.mocked(operationsApi.delivery).mockRejectedValueOnce(new ApiError({ status: 503 }))
    const wrapper = push(); await tick()
    expect(wrapper.text()).toContain('服务暂时不可用')
    await vi.advanceTimersByTimeAsync(5000)
    expect(operationsApi.delivery).toHaveBeenCalledTimes(2); expect(operationsApi.policy).toHaveBeenCalledOnce()
    let resolve!: (value: DeliveryStatus) => void, signal!: AbortSignal
    vi.mocked(operationsApi.delivery).mockImplementationOnce(s => { signal = s!; return new Promise(done => { resolve = done }) })
    await vi.advanceTimersByTimeAsync(30000); projectScope.clear(); expect(signal.aborted).toBe(true)
    resolve(delivery(999)); await tick(); expect(wrapper.text()).not.toContain('999')
    const count = vi.mocked(operationsApi.delivery).mock.calls.length
    await vi.advanceTimersByTimeAsync(90000); expect(operationsApi.delivery).toHaveBeenCalledTimes(count)
  })
  it('polls idle at 30s and pending at 5s without reloading the policy', async () => {
    const wrapper = push(); await tick(); expect(operationsApi.policy).toHaveBeenCalledOnce()
    await vi.advanceTimersByTimeAsync(29999); expect(operationsApi.delivery).toHaveBeenCalledOnce()
    vi.mocked(operationsApi.delivery).mockResolvedValue(delivery(1))
    await vi.advanceTimersByTimeAsync(1); expect(operationsApi.delivery).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(5000); expect(operationsApi.delivery).toHaveBeenCalledTimes(3)
    hidden(true); await vi.advanceTimersByTimeAsync(60000); expect(operationsApi.delivery).toHaveBeenCalledTimes(3)
    hidden(false); await tick(); expect(operationsApi.delivery).toHaveBeenCalledTimes(4)
    expect(operationsApi.policy).toHaveBeenCalledOnce(); expect(wrapper.text()).toContain('待处理 1')
  })
  it('tracks explicit test receipt to completion, never infers success and never reloads policy', async () => {
    const write = vi.spyOn(operationsApi, 'testDelivery').mockResolvedValue({ accepted: true, deliveryIds: ['test-1'] })
    const wrapper = push(); await tick(); await click(wrapper, '测试 移动端通知')
    wrapper.findComponent({ name: 'UiConfirmDialog' }).vm.$emit('confirm'); await tick()
    expect(write).toHaveBeenCalledOnce(); expect(operationsApi.policy).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('测试回执尚未确认')
    await vi.advanceTimersByTimeAsync(5000); expect(operationsApi.delivery).toHaveBeenCalledTimes(3)
    vi.mocked(operationsApi.delivery).mockResolvedValue({ ...delivery(), recent: [{ delivery_id: 'test-1', channel: 'app', status: 'failed', attempts: 3 }] })
    await vi.advanceTimersByTimeAsync(5000); expect(wrapper.text()).not.toContain('测试回执尚未确认')
    await vi.advanceTimersByTimeAsync(29999); expect(operationsApi.delivery).toHaveBeenCalledTimes(4)
    expect(write).toHaveBeenCalledOnce(); expect(operationsApi.policy).toHaveBeenCalledOnce()
  })
  it('does not resend an uncertain test and stops on capability loss', async () => {
    const write = vi.spyOn(operationsApi, 'testDelivery').mockRejectedValue(new ApiError({ kind: 'timeout' }))
    const wrapper = push(); await tick(); await click(wrapper, '测试 移动端通知')
    wrapper.findComponent({ name: 'UiConfirmDialog' }).vm.$emit('confirm'); await tick()
    await vi.advanceTimersByTimeAsync(60000); expect(write).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('不会自动重试'); expect(operationsApi.policy).toHaveBeenCalledOnce()
    const count = vi.mocked(operationsApi.delivery).mock.calls.length
    useProjectsStore().phase = 'unavailable'; await tick(); await vi.advanceTimersByTimeAsync(90000)
    expect(operationsApi.delivery).toHaveBeenCalledTimes(count)
    expect(wrapper.text()).not.toContain('通道运行状态')
  })
  it('keeps missing test receipts unconfirmed but bounds fast polling to one minute', async () => {
    vi.spyOn(operationsApi, 'testDelivery').mockResolvedValue({ accepted: true, deliveryIds: ['missing'] })
    const wrapper = push(); await tick(); await click(wrapper, '测试 移动端通知')
    wrapper.findComponent({ name: 'UiConfirmDialog' }).vm.$emit('confirm'); await tick()
    await vi.advanceTimersByTimeAsync(60000)
    const count = vi.mocked(operationsApi.delivery).mock.calls.length
    await vi.advanceTimersByTimeAsync(29999); expect(operationsApi.delivery).toHaveBeenCalledTimes(count)
    await vi.advanceTimersByTimeAsync(1); expect(operationsApi.delivery).toHaveBeenCalledTimes(count + 1)
    expect(wrapper.text()).toContain('测试回执尚未确认')
  })
})
