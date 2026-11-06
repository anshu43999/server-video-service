// @vitest-environment happy-dom
import {expect,it} from 'vitest'
import {mount} from '@vue/test-utils'
import {defaultCameraPolicy,cameraPolicyError} from '../src/features/scenes/cameraPolicy'
import {planPayload} from '../src/features/scenes/presentation'
import CameraPolicyFields from '../src/features/scenes/CameraPolicyFields.vue'
import {installUiComponents} from '../src/components/ui/plugin'
it('validates integral bounded camera settings without sharing defaults',()=>{
  const a=defaultCameraPolicy();a.frameInterval=17
  expect(defaultCameraPolicy().frameInterval).toBe(5)
  for(const changes of [{frameInterval:0},{frameInterval:1.5},{batchTimeoutMs:750},{resultMaxAgeMs:4999},{overlayHoldMs:3001}])expect(cameraPolicyError({...defaultCameraPolicy(),...changes})).not.toBe('')
  expect(cameraPolicyError(a)).toBe('')
})
it('keeps policy in write payload without leaking approved projections',()=>{
  const policy={...defaultCameraPolicy(),frameInterval:12}
  const input={planId:'camera',name:'相机',inputTypes:['video' as const],memberIds:['m'],execution:'single' as const,enabled:true,cameraPolicy:policy,implicit:true}
  const payload=planPayload(input)
  expect(payload.cameraPolicy).toEqual(policy);expect(payload).not.toHaveProperty('implicit')
  payload.cameraPolicy!.frameInterval=20;expect(policy.frameInterval).toBe(12)
})
it('labels frame and time semantics and updates an immutable policy',async()=>{
  const policy=defaultCameraPolicy()
  const wrapper=mount(CameraPolicyFields,{props:{modelValue:policy},global:{plugins:[installUiComponents]}})
  expect(wrapper.text()).toContain('识别抽帧间隔');expect(wrapper.text()).toContain('同步模型识别同一选中帧')
  wrapper.findAllComponents({name:'UiInput'})[0]!.vm.$emit('update:modelValue',8)
  expect(wrapper.emitted('update:modelValue')![0]![0]).toEqual({...policy,frameInterval:8})
  expect(policy.frameInterval).toBe(5);wrapper.unmount()
})
