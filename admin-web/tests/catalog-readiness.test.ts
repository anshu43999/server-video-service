// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { installUiComponents } from '../src/components/ui/plugin'
import { catalogReadiness } from '../src/features/models/catalogReadiness'
import CatalogReadiness from '../src/features/models/CatalogReadiness.vue'
import ModelsView from '../src/features/models/ModelsView.vue'
import { modelsApi } from '../src/features/models/api'
import type { ModelAsset } from '../src/features/models/types'

const model = (): ModelAsset => ({
  modelId: 'phone', name: '手机检测', version: '1.0.0', status: 'PUBLISHED', releaseEligible: true,
  supportedTargets: ['pc', 'mobile'], serverReady: true, androidReady: true,
  targetReleaseEligible: { pc: true, mobile: true },
  parameterPublication: {
    server: { state: 'unpublished', publishedRevision: null, hasUnpublishedChanges: true },
    android: { state: 'published', publishedRevision: 0, hasUnpublishedChanges: false },
  },
})
afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = '' })

it('distinguishes unpublished parameters, revision zero and a newer unpublished draft', () => {
  const asset = model()
  expect(catalogReadiness(asset, 'pc')).toMatchObject({
    status: '待发布参数', parameters: '尚未发布', action: '去发布服务端参数',
  })
  expect(catalogReadiness(asset, 'mobile')).toMatchObject({ status: '项目可添加', parameters: '已发布 r0' })
  asset.parameterPublication!.android!.hasUnpublishedChanges = true
  expect(catalogReadiness(asset, 'mobile')).toMatchObject({ status: '项目可添加', parameters: '已发布 r0 · 有新草稿' })
  expect(catalogReadiness(asset, 'mobile').hint).toContain('仍使用已发布参数 r0')
})

it('never treats unknown or failed parameter status as unpublished or ready', () => {
  for (const publication of [undefined, { state: 'unavailable' as const, publishedRevision: null, hasUnpublishedChanges: false }]) {
    const asset = model()
    asset.parameterPublication!.server = publication
    expect(catalogReadiness(asset, 'pc')).toMatchObject({ status: '状态待核实', parameters: '状态待核实', action: '查看服务端参数' })
  }
})

it('does not claim project availability when files or version are ineligible', () => {
  const asset = model()
  asset.androidReady = false
  expect(catalogReadiness(asset, 'mobile').status).toBe('暂不可添加')
  expect(catalogReadiness(asset, 'mobile').hint).toContain('完成该端产物处理')
  asset.androidReady = true
  asset.status = 'REVOKED'
  expect(catalogReadiness(asset, 'mobile').status).toBe('暂不可添加')
  expect(catalogReadiness(asset, 'mobile').hint).toContain('核查版本状态')
})

it('shows supported ends only and emits the matching parameter platform', async () => {
  const asset = model()
  asset.supportedTargets = ['pc']
  const wrapper = mount(CatalogReadiness, { props: { model: asset }, global: { plugins: [installUiComponents] } })
  expect(wrapper.text()).toContain('尚未出现在项目')
  expect(wrapper.text()).not.toContain('Android')
  await wrapper.get('button').trigger('click')
  expect(wrapper.emitted('parameters')).toEqual([['server']])
  wrapper.unmount()
})

it('opens parameters for the exact release and end, then refreshes catalog status on closing', async () => {
  const asset = model()
  const list = vi.spyOn(modelsApi, 'list').mockResolvedValue([asset])
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: ModelsView }] })
  await router.push('/')
  const wrapper = mount(ModelsView, {
    global: { plugins: [installUiComponents, router], stubs: {
      UiDialog: { name: 'UiDialog', props: ['open'], template: '<section v-if="open"><slot/></section>' },
      ParametersDialog: { name: 'ParametersDialog', props: ['model', 'initialPlatform'], emits: ['close'], template: '<aside>参数档案</aside>' },
    } },
  })
  await flushPromises()
  expect(wrapper.find('.model-tags').text()).toContain('模型文件已发布')
  expect(wrapper.find('.model-tags').text()).not.toContain('PUBLISHED')
  await wrapper.findAll('button').find(b => b.text() === '去发布服务端参数')!.trigger('click')
  const dialog = wrapper.findComponent({ name: 'ParametersDialog' })
  expect(dialog.props('model')).toEqual(asset)
  expect(dialog.props('initialPlatform')).toBe('server')
  list.mockResolvedValue([{ ...asset, parameterPublication: {
    ...asset.parameterPublication, server: { state: 'published', publishedRevision: 1, hasUnpublishedChanges: false },
  } }])
  dialog.vm.$emit('close')
  await flushPromises()
  expect(list).toHaveBeenCalledTimes(2)
  expect(wrapper.find('.catalog-readiness-row').text()).toContain('项目可添加')
  expect(wrapper.find('.catalog-readiness-row').text()).toContain('已发布 r1')
  wrapper.unmount()
})
