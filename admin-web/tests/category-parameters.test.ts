// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ParametersDialog from '../src/features/models/ParametersDialog.vue'
import { installUiComponents } from '../src/components/ui/plugin'
import { scenesApi } from '../src/features/scenes/api'
import type { ModelAsset, ParameterProfile } from '../src/features/models/types'

afterEach(()=>vi.restoreAllMocks())
it('uses one class switch, saves a scene override and advances the scene CAS for another save',async()=>{
  const profile={schemaVersion:2,modelId:'model',modelVersion:'1',platform:'android',revision:0,sceneRevision:2,source:'default',
    detection:{confidenceThreshold:.35,iouThreshold:.45,maxDetections:100},alertRules:[{rawLabel:'first',displayName:'第一类',eventCode:'FIRST',operator:'PRESENCE',enabled:true,severity:'MAJOR',image:{minimumConfidence:.55,cooldownMs:0},camera:{minimumConfidence:.55,minimumConsecutiveFrames:1,minimumDwellTimeMs:0,cooldownMs:0}}]} as ParameterProfile
  vi.spyOn(scenesApi,'profile').mockResolvedValue(structuredClone(profile))
  const save=vi.spyOn(scenesApi,'saveProfile').mockImplementation(async(_binding,value)=>({...JSON.parse(JSON.stringify(value)),revision:value.revision+1,sceneRevision:(value.sceneRevision??2)+1}))
  const wrapper=mount(ParametersDialog,{props:{model:{modelId:'model',version:'1',name:'模型'} as ModelAsset,initialPlatform:'android',projectMode:true,sceneBinding:{sceneId:'scene',memberId:'member',revision:2}},global:{plugins:[installUiComponents],config:{warnHandler:()=>{}},stubs:{UiDialog:{template:'<section><slot/></section>'},UiConfirmDialog:true}}})
  await flushPromises()
  expect(wrapper.text()).toContain('启用识别与告警')
  expect(wrapper.text()).not.toContain('启用该类别告警')
  expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(1)
  await wrapper.find('input[type="checkbox"]').setValue(false)
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(save.mock.calls[0]?.[0].revision).toBe(2)
  expect(save.mock.calls[0]?.[1].alertRules[0]?.enabled).toBe(false)
  expect(wrapper.text()).toContain('请重新审批该场景后运行')
  await wrapper.find('form').trigger('submit');await flushPromises()
  expect(save.mock.calls[1]?.[0].revision).toBe(3)
  wrapper.unmount()
})
