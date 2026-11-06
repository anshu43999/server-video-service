// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import UiConfirmDialog from '../src/components/ui/UiConfirmDialog.vue'
import UiDataTable from '../src/components/ui/UiDataTable.vue'
import UiInput from '../src/components/ui/UiInput.vue'
import UiOption from '../src/components/ui/UiOption.vue'
import UiSelect from '../src/components/ui/UiSelect.vue'
import UiStatePanel from '../src/components/ui/UiStatePanel.vue'
import UiTag from '../src/components/ui/UiTag.vue'

afterEach(() => { document.body.innerHTML = '' })

describe('shared state components', () => {
  it.each([
    ['loading', '正在加载'],
    ['empty', '暂无数据'],
    ['error', '数据不可用'],
  ] as const)('renders the %s state with truthful default copy', (state, title) => {
    const wrapper = mount(UiStatePanel, { props: { state } })
    expect(wrapper.text()).toContain(title)
    expect(wrapper.attributes('aria-busy')).toBe(state === 'loading' ? 'true' : 'false')
    expect(wrapper.find('button').exists()).toBe(state === 'error')
  })

  it('renders a semantic empty table without inventing rows', () => {
    const wrapper = mount(UiDataTable, { props: { caption: '告警列表', columns: [{ key: 'name', label: '名称' }], rows: [] } })
    expect(wrapper.attributes('aria-label')).toBe('告警列表')
    expect(wrapper.find('.el-table').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无数据')
  })
  it('forwards optional sizing and fixed operation columns without changing defaults', () => {
    const wrapper=mount(UiDataTable,{props:{caption:'场景列表',columns:[{key:'name',label:'名称',minWidth:240,align:'start'},{key:'actions',label:'操作',width:110,fixed:'right'}],rows:[{id:'s1',name:'场景'}]}})
    const columns=wrapper.findAllComponents({name:'ElTableColumn'})
    expect(columns[0]!.props()).toMatchObject({minWidth:240,align:'left'})
    expect(columns[1]!.props()).toMatchObject({width:110,fixed:'right'})
    wrapper.unmount()
  })
})

describe('Element Plus control adapters', () => {
  it('keeps the server supplied switch state until the parent accepts a change', async () => {
    const wrapper = mount(UiInput, { props: { type: 'checkbox', checked: true } })
    expect(wrapper.find('[role="switch"]').attributes('aria-checked')).toBe('true')
    await wrapper.find('.el-switch').trigger('click')
    expect(wrapper.emitted('change')).toEqual([[false]])
    expect(wrapper.find('[role="switch"]').attributes('aria-checked')).toBe('true')
    await wrapper.setProps({ checked: false })
    expect(wrapper.find('[role="switch"]').attributes('aria-checked')).toBe('false')
    wrapper.unmount()
  })
  it('uses Element Plus switch and forwards its value', async () => {
    const wrapper = mount(UiInput, { props: { type: 'checkbox', modelValue: false } })
    wrapper.findComponent({ name: 'ElSwitch' }).vm.$emit('change', true)
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([[true]])
    expect(wrapper.find('.el-switch').exists()).toBe(true)
  })

  it('uses Element Plus select and option adapters with controlled values', async () => {
    const wrapper = mount(UiSelect, {
      props: { value: 'helmet' },
      slots: { default: '<UiOption value="helmet">安全帽</UiOption><UiOption value="person">人员</UiOption>' },
      global: { components: { UiOption } },
    })
    expect(wrapper.find('.el-select').exists()).toBe(true)
    expect(wrapper.findAllComponents(UiOption)[0]?.findComponent({ name: 'ElOption' }).props('label')).toBe('安全帽')
    wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('change', 'person')
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([['person']])
  })

  it('renders shared status labels through Element Plus', () => {
    const wrapper = mount(UiTag, { props: { tone: 'success' }, slots: { default: '已就绪' } })
    expect(wrapper.find('.el-tag').exists()).toBe(true)
    expect(wrapper.text()).toBe('已就绪')
  })
})

describe('confirmation dialog accessibility', () => {
  it('focuses cancel, closes on Escape, restores focus, and never confirms cancellation', async () => {
    const opener = document.createElement('button')
    opener.textContent = '删除模型'
    document.body.append(opener)
    opener.focus()
    const wrapper = mount(UiConfirmDialog, {
      attachTo: document.body,
      props: { open: false, title: '确认删除', description: '删除后无法直接恢复。', tone: 'danger' },
    })

    await wrapper.setProps({ open: true })
    await nextTick()
    const cancel = document.querySelector<HTMLButtonElement>('.confirm-dialog .secondary-button')
    const dialog = document.querySelector<HTMLElement>('.confirm-dialog')
    const dialogContainer = document.querySelector<HTMLElement>('.el-overlay-dialog')
    expect(dialogContainer?.getAttribute('role')).toBe('alertdialog')
    expect(dialogContainer?.getAttribute('aria-label')).toBe('确认删除')
    expect(document.activeElement).toBe(cancel)

    dialog?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()
    expect(wrapper.emitted('update:open')).toEqual([[false]])
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(document.activeElement).toBe(opener)
    wrapper.unmount()
  })

  it('emits confirmation only from the explicit confirm button', async () => {
    const wrapper = mount(UiConfirmDialog, {
      attachTo: document.body,
      props: { open: true, title: '确认操作', description: '继续执行当前操作。' },
    })
    await nextTick()
    await document.querySelector<HTMLButtonElement>('.confirm-dialog .primary-button')?.click()
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toBeUndefined()
    wrapper.unmount()
  })
})
