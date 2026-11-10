// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { useCandidates } from '../src/features/management/useCandidates'
import { projectScope } from '../src/api/projectScope'
afterEach(()=>{projectScope.clear();projectScope.enabled=false;vi.restoreAllMocks()})
const setup=(load:(s:AbortSignal)=>Promise<string[]>)=>{
  const visible=ref(false);let state!:ReturnType<typeof useCandidates<string>>
  const wrapper=mount(defineComponent({setup(){state=useCandidates(visible,load);return()=>null}}))
  return {visible,state,wrapper}
}
it('does not load hidden candidates, rereads each opening and cancels close',async()=>{
  let resolve!:(v:string[])=>void,signal!:AbortSignal
  const load=vi.fn((s:AbortSignal)=>{signal=s;return new Promise<string[]>(r=>{resolve=r})})
  const {visible,state,wrapper}=setup(load);await flushPromises();expect(load).not.toHaveBeenCalled()
  visible.value=true;await flushPromises();expect(state.loading.value).toBe(true)
  visible.value=false;await flushPromises();expect(signal.aborted).toBe(true)
  resolve(['late-private']);await flushPromises();expect(state.data.value).toEqual([])
  load.mockResolvedValueOnce(['fresh']);visible.value=true;await flushPromises()
  expect(state.data.value).toEqual(['fresh']);expect(load).toHaveBeenCalledTimes(2);wrapper.unmount()
})
it('shows candidate errors independently and retries without hiding page data',async()=>{
  const load=vi.fn().mockRejectedValueOnce(new Error('failed')).mockResolvedValue(['ok'])
  const {visible,state,wrapper}=setup(load);visible.value=true;await flushPromises()
  expect(state.error.value).toBeTruthy();expect(state.loading.value).toBe(false)
  await state.refresh();expect(state.error.value).toBe('');expect(state.data.value).toEqual(['ok']);wrapper.unmount()
})
it('clears private candidates and rejects pending data on scope revocation',async()=>{
  projectScope.enable();let resolve!:(v:string[])=>void,signal!:AbortSignal
  const {visible,state,wrapper}=setup(s=>{signal=s;return new Promise(r=>{resolve=r})})
  visible.value=true;await flushPromises();projectScope.clear();expect(signal.aborted).toBe(true)
  resolve(['old-account']);await flushPromises();expect(state.data.value).toEqual([]);wrapper.unmount()
})
