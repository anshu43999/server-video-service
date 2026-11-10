// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/errors'
import { mount } from '@vue/test-utils'
import AlertDetailDialog from '../src/features/alerts/AlertDetailDialog.vue'
import { alertsApi } from '../src/features/alerts/api'
import UiButton from '../src/components/ui/UiButton.vue'
import UiInput from '../src/components/ui/UiInput.vue'

vi.mock('../src/features/projects/capabilities', () => ({ useProjectCapabilities: () => ({ dispose: true }) }))
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
beforeEach(() => {
  // happy-dom has no layout intersection delivery; these dialogs are visible.
  vi.stubGlobal('IntersectionObserver', class {
    constructor(private callback: IntersectionObserverCallback) {}
    observe(target: Element) { this.callback([{ target, isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver) }
    disconnect() {}
  })
  vi.spyOn(alertsApi, 'latestAdvice').mockRejectedValue(new ApiError({ status: 404, code: 'ADVICE_GENERATION_NOT_FOUND' }))
})
const event = { eventId: 'event-1', projectId: 'project-a', ruleId: 'PPE_NO_HELMET', label: 'HEAD', disposition: { status: 'OPEN' } }
const generated = { contractVersion: '1.0', generationId: 'g-1', projectId: 'project-a', eventId: 'event-1', requestedBy: 'operator', idempotencyKey: crypto.randomUUID(), status: 'GENERATED', matchKey: { alertTypeId: 'PPE_NO_HELMET', recognitionCategoryId: 'HEAD' }, advice: { title: '安全帽处置建议', steps: [{ stepId: 'stop', order: 1, title: '暂停作业', instruction: '先撤离风险区' }], cautions: [] }, references: [{ referenceId: 'r', documentTitle: '安全制度', documentVersion: 'v1', clauseId: 'PPE-1', excerpt: '应佩戴安全帽', sourceName: '模拟库', sourceType: 'MOCK_KNOWLEDGE_BASE' }], knowledgeRevision: 1, retrievalProvider: 'SIMULATED_KNOWLEDGE_BASE', generationProvider: 'SIMULATED_LLM', sourceNotice: '模拟结果', error: null, createdAt: '2026-01-01T00:00:00Z', completedAt: '2026-01-01T00:00:01Z' }
describe('alert advice detail interaction', () => {
  it('reloads changed thumbnail metadata without clearing notes or replacing a selected original', async () => {
    const evidence = vi.spyOn(alertsApi, 'evidence').mockResolvedValue(new Blob(['thumbnail']))
    const original = vi.spyOn(alertsApi, 'originalEvidence').mockResolvedValue(new Blob(['original']))
    vi.spyOn(URL, 'createObjectURL').mockImplementation(() => `blob:${crypto.randomUUID()}`)
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const current = { ...event, origin: 'MOBILE_CAMERA', originalRequest: { status: 'UPLOADED', contentVersion: 1 } }
    const wrapper = mount(AlertDetailDialog, { attachTo: document.body, global: { components: { UiButton, UiInput } },
      props: { open: true, event: current as never, detailPhase: 'ready' } })
    try {
      await vi.waitFor(() => expect(evidence).toHaveBeenCalledOnce())
      const note = document.body.querySelector('textarea') as HTMLTextAreaElement
      note.value = '保留备注'; note.dispatchEvent(new Event('input', { bubbles: true }))
      await wrapper.setProps({ event: { ...current, evidence: { snapshotUri: 'new-thumbnail' } } as never })
      await vi.waitFor(() => expect(evidence).toHaveBeenCalledTimes(2))
      expect(note.value).toBe('保留备注')
      ;[...document.body.querySelectorAll('button')].find(node => node.textContent?.includes('查看已上传原图'))!.click()
      await vi.waitFor(() => expect(original).toHaveBeenCalledOnce())
      await vi.waitFor(() => expect(document.body.querySelector('.alert-detail-dialog img')).not.toBeNull())
      const image = document.body.querySelector('.alert-detail-dialog img')!
      await wrapper.setProps({ event: { ...current, evidence: { snapshotUri: 'third-thumbnail' } } as never })
      expect(evidence).toHaveBeenCalledTimes(2)
      expect(document.body.querySelector('.alert-detail-dialog img')).toBe(image)
      expect(note.value).toBe('保留备注')
    } finally { wrapper.unmount() }
  })

  it('rejects late history from a closed or different project even with the same event ID', async () => {
    vi.spyOn(alertsApi, 'evidence').mockResolvedValue(new Blob())
    vi.spyOn(alertsApi, 'generateAdvice').mockResolvedValue(generated as never)
    let finish!: (value: { generations: typeof generated[] }) => void
    vi.spyOn(alertsApi, 'adviceHistory').mockImplementation(() => new Promise(resolve => { finish = resolve as typeof finish }))
    const wrapper = mount(AlertDetailDialog, { attachTo: document.body, global: { components: { UiButton, UiInput } },
      props: { open: true, event: event as never, detailPhase: 'ready' } })
    try {
      await wrapper.vm.$nextTick()
      await vi.waitFor(() => expect(document.body.textContent).toContain('暂无已保存'))
      ;[...document.body.querySelectorAll('button')].find(node => node.textContent?.includes('生成建议'))!.click()
      await vi.waitFor(() => expect(document.body.textContent).toContain('安全帽处置建议'))
      ;[...document.body.querySelectorAll('button')].find(node => node.textContent?.trim() === '历史')!.click()
      await wrapper.setProps({ event: { ...event, projectId: 'project-b' } as never })
      finish({ generations: [generated] })
      await wrapper.vm.$nextTick(); await wrapper.vm.$nextTick()
      expect(document.body.querySelector('.advice-history')).toBeNull()
      await wrapper.setProps({ open: false })
      expect(document.body.querySelector('.alert-detail-dialog')).toBeNull()
    } finally { wrapper.unmount() }
  })
  it('keeps notes, advice, focus and evidence while the same alert snapshot refreshes', async () => {
    const evidence = vi.spyOn(alertsApi, 'evidence').mockResolvedValue(new Blob(['image']))
    vi.spyOn(alertsApi, 'generateAdvice').mockResolvedValue(generated as never)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:stable')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const wrapper = mount(AlertDetailDialog, { attachTo: document.body, global: { components: { UiButton, UiInput } },
      props: { open: true, event: event as never, detailPhase: 'ready' } })
    try {
      await vi.waitFor(() => expect(evidence).toHaveBeenCalledOnce())
      const dialog = document.body.querySelector('.alert-detail-dialog') as HTMLElement
      const note = document.body.querySelector('textarea') as HTMLTextAreaElement
      note.value = '正在核对现场'; note.dispatchEvent(new Event('input', { bubbles: true })); note.focus()
      await vi.waitFor(() => expect(dialog.textContent).toContain('暂无已保存'))
      const generate = [...dialog.querySelectorAll('button')].find(node => node.textContent?.includes('生成建议'))!
      generate.click()
      await vi.waitFor(() => expect(dialog.textContent).toContain('安全帽处置建议'))
      dialog.scrollTop = 320
      const image = dialog.querySelector('img')
      for (let index = 0; index < 5; index++) {
        await wrapper.setProps({ event: { ...event, lastSeenAtUs: index } as never })
        expect(dialog.scrollTop).toBe(320)
        expect(document.activeElement).toBe(note)
        expect(note.value).toBe('正在核对现场')
        expect(dialog.textContent).toContain('安全帽处置建议')
        expect(dialog.querySelector('img')).toBe(image)
      }
      expect(evidence).toHaveBeenCalledOnce()
      await wrapper.setProps({ event: { ...event, disposition: { status: 'ACKNOWLEDGED' } } as never })
      expect(note.value).toBe('正在核对现场')
      expect(dialog.textContent).toContain('已确认')
      await wrapper.setProps({ open: false }); await wrapper.setProps({ open: true })
      await vi.waitFor(() => expect(evidence).toHaveBeenCalledTimes(2))
      expect((document.body.querySelector('textarea') as HTMLTextAreaElement).value).toBe('')
      expect(document.body.textContent).not.toContain('安全帽处置建议')
    } finally { wrapper.unmount() }
  })
  it('does not generate on open and clears old advice when event changes', async () => {
    vi.spyOn(alertsApi, 'evidence').mockResolvedValue(new Blob())
    const generate = vi.spyOn(alertsApi, 'generateAdvice').mockResolvedValue(generated as never)
    const wrapper = mount(AlertDetailDialog, { attachTo: document.body, global: { components: { UiButton, UiInput } }, props: { open: true, event: event as never, detailPhase: 'ready' } })
    await wrapper.vm.$nextTick(); expect(generate).not.toHaveBeenCalled()
    await vi.waitFor(() => expect(document.body.textContent).toContain('暂无已保存'))
    const button = [...document.body.querySelectorAll('button')].find(node => node.textContent?.includes('生成建议')) as HTMLButtonElement
    button.click(); await vi.waitFor(() => expect(generate).toHaveBeenCalledOnce())
    await vi.waitFor(() => expect(document.body.textContent).toContain('安全帽处置建议'))
    await wrapper.setProps({ event: { ...event, eventId: 'event-2' } as never }); await wrapper.vm.$nextTick()
    expect(document.body.textContent).not.toContain('安全帽处置建议')
    await vi.waitFor(() => expect(document.body.textContent).toContain('打开详情只读取已保存结果'))
    wrapper.unmount()
  })
  it('reads the shared saved result on each entry, without generating or re-reading on polling', async () => {
    const latest = vi.mocked(alertsApi.latestAdvice).mockResolvedValue(generated as never)
    const generate = vi.spyOn(alertsApi, 'generateAdvice')
    vi.spyOn(alertsApi, 'evidence').mockResolvedValue(new Blob())
    vi.spyOn(alertsApi, 'adviceHistory').mockResolvedValue({ generations: [generated] } as never)
    const wrapper = mount(AlertDetailDialog, { attachTo: document.body, global: { components: { UiButton, UiInput } }, props: { open: true, event: event as never, detailPhase: 'ready' } })
    try {
      await vi.waitFor(() => expect(document.body.textContent).toContain('安全帽处置建议'))
      for (let i = 0; i < 3; i++) await wrapper.setProps({ event: { ...event, lastSeenAtUs: i } as never })
      expect(latest).toHaveBeenCalledOnce(); expect(generate).not.toHaveBeenCalled()
      ;[...document.body.querySelectorAll('button')].find(node => node.textContent?.trim() === '历史')!.click()
      await vi.waitFor(() => expect(document.body.querySelector('.advice-history')?.textContent).toContain('g-1'))
      await wrapper.setProps({ open: false }); await wrapper.setProps({ open: true })
      await vi.waitFor(() => expect(latest).toHaveBeenCalledTimes(2))
      expect(generate).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
  it('retries read failures with GET only and rejects late reads after a project switch', async () => {
    const latest = vi.mocked(alertsApi.latestAdvice).mockRejectedValue(new ApiError({ status: 503 }))
    const generate = vi.spyOn(alertsApi, 'generateAdvice')
    vi.spyOn(alertsApi, 'evidence').mockResolvedValue(new Blob())
    const wrapper = mount(AlertDetailDialog, { attachTo: document.body, global: { components: { UiButton, UiInput } }, props: { open: true, event: event as never, detailPhase: 'ready' } })
    try {
      await vi.waitFor(() => expect(document.body.textContent).toContain('已保存建议读取失败'))
      let finish!: (value: typeof generated) => void
      latest.mockImplementationOnce(() => new Promise(resolve => { finish = resolve as typeof finish }))
      ;[...document.body.querySelectorAll('button')].find(node => node.textContent?.trim() === '重新读取')!.click()
      await vi.waitFor(() => expect(latest).toHaveBeenCalledTimes(2))
      await wrapper.setProps({ event: { ...event, projectId: 'project-b' } as never })
      finish(generated)
      await vi.waitFor(() => expect(latest).toHaveBeenCalledTimes(3))
      expect(document.body.textContent).not.toContain('安全帽处置建议')
      expect(generate).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
})
