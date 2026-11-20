// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'
import KnowledgeView from '../src/features/advice/KnowledgeView.vue'
import { alertAdviceApi, systemKnowledgeApi, type KnowledgeEntry } from '../src/features/advice/api'
import UiButton from '../src/components/ui/UiButton.vue'
import UiInput from '../src/components/ui/UiInput.vue'

const state = vi.hoisted(() => ({ projects: null as any }))
vi.mock('../src/stores/projects', () => ({ useProjectsStore: () => state.projects }))
const entry: KnowledgeEntry = {
  entryId: 'helmet', projectId: 'system', origin: 'SYSTEM', systemVersion: 3,
  matchKey: { alertTypeId: 'PPE_NO_HELMET', recognitionCategoryId: 'HEAD' }, status: 'ACTIVE', revision: 2,
  title: '安全帽参考资料', riskDescription: '现场风险', applicability: '现场核实', sourceType: 'MOCK_KNOWLEDGE_BASE',
  adviceTemplate: { title: '建议', steps: [{ stepId: 'one', order: 1, title: '暂停', instruction: '先撤离风险区' }], cautions: [] },
  references: [{ referenceId: 'ref', documentTitle: '模拟制度', documentNumber: null, documentVersion: 'v1', chapter: null, clauseId: '1', excerpt: '条款原文', sourceName: '模拟资料', sourceType: 'MOCK_KNOWLEDGE_BASE', effectiveDate: null }],
  createdBy: 'admin', updatedBy: 'admin', createdAt: '2026-11-16T00:00:00Z', updatedAt: '2026-11-16T00:00:00Z',
}
const options = { attachTo: document.body, global: { components: { UiButton, UiInput } } }
beforeEach(() => {
  state.projects = reactive({ current: { projectId: 'project-a', lifecycleState: 'ACTIVE', capabilities: ['project.alert_knowledge.read', 'project.alert_knowledge.manage'] } })
  vi.spyOn(alertAdviceApi, 'catalog').mockResolvedValue({ entries: [{ ...entry, entryId: 'system:helmet', projectId: 'project-a' }], systemVersion: 3 })
  vi.spyOn(systemKnowledgeApi, 'catalog').mockResolvedValue({ entries: [entry], revision: 4 })
  vi.spyOn(systemKnowledgeApi, 'versions').mockResolvedValue({ versions: [] })
})
afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = '' })
describe('system-only knowledge maintenance', () => {
  it('renders project knowledge read-only even if a stale session still advertises manage', async () => {
    const wrapper = mount(KnowledgeView, { ...options, props: { system: false } })
    try {
      await flushPromises()
      expect(wrapper.text()).toContain('当前发布 V3')
      const buttons = wrapper.findAll('button').map(node => node.text())
      expect(buttons).toContain('查看详情')
      expect(buttons).not.toContain('编辑')
      expect(buttons).not.toContain('停用')
      expect(buttons.join(' ')).not.toMatch(/新增|升级|覆盖|发布系统/)
      expect(wrapper.find('.knowledge-form').exists()).toBe(false)
      expect(systemKnowledgeApi.catalog).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
  it('edits SYSTEM-origin drafts through the platform API, never through project overrides', async () => {
    const update = vi.spyOn(systemKnowledgeApi, 'update').mockResolvedValue({ ...entry, revision: 3 })
    const wrapper = mount(KnowledgeView, { ...options, props: { system: true } })
    try {
      await flushPromises()
      await wrapper.findAll('button').find(node => node.text() === '编辑')!.trigger('click')
      await flushPromises()
      const form = document.body.querySelector('.knowledge-form')!
      expect(form).not.toBeNull()
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      await flushPromises()
      expect(update).toHaveBeenCalledOnce()
      expect(update.mock.calls[0]![0].entryId).toBe('helmet')
      expect(alertAdviceApi.catalog).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
  it('changes system draft status only through the platform API', async () => {
    const status = vi.spyOn(systemKnowledgeApi, 'status').mockResolvedValue({ ...entry, status: 'INACTIVE', revision: 3 })
    const wrapper = mount(KnowledgeView, { ...options, props: { system: true } })
    try {
      await flushPromises()
      await wrapper.findAll('button').find(node => node.text() === '停用')!.trigger('click')
      await flushPromises()
      expect(status).toHaveBeenCalledWith(expect.objectContaining({ entryId: 'helmet' }), 'INACTIVE')
    } finally { wrapper.unmount() }
  })
  it('does not display a late catalog from a previous project', async () => {
    let finish!: (value: any) => void
    vi.mocked(alertAdviceApi.catalog).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mount(KnowledgeView, { ...options, props: { system: false } })
    try {
      state.projects.current.projectId = 'project-b'
      await flushPromises()
      finish({ entries: [{ ...entry, title: '旧项目迟到资料' }], systemVersion: 1 })
      await flushPromises()
      expect(wrapper.text()).not.toContain('旧项目迟到资料')
      expect(wrapper.text()).toContain('当前发布 V3')
    } finally { wrapper.unmount() }
  })
})
