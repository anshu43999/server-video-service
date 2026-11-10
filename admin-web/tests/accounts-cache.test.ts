// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import AccountsView from '../src/features/management/AccountsView.vue'
import { managementApi, type AccountRecord } from '../src/features/management/api'
import { useManagementReadContext } from '../src/features/management/readContext'
import { managementReads } from '../src/api/readCache'
import { projectScope } from '../src/api/projectScope'
import { ApiError } from '../src/api/errors'
import { ApiClient } from '../src/api/client'
import { useSessionStore } from '../src/stores/session'
import { useProjectsStore } from '../src/stores/projects'
const row = (): AccountRecord => ({accountId:'other',username:'fixture-account',platformRole:'NORMAL_USER',enabled:true,revision:1})
let pinia: ReturnType<typeof createPinia>
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(()=>{
  pinia=createPinia();setActivePinia(pinia);projectScope.enable()
  const session=useSessionStore();session.phase='authenticated'
  session.user={accountId:'admin',username:'fixture-admin',role:'admin',platformRole:'PLATFORM_ADMIN',contractVersion:'m33-v1'}
  useProjectsStore().platformReady=true
})
afterEach(()=>{wrappers.splice(0).forEach(w=>w.unmount());projectScope.clear();disposePinia(pinia);projectScope.enabled=false;vi.useRealTimers();vi.restoreAllMocks()})
function page(){
  const wrapper=mount(AccountsView,{global:{plugins:[pinia],stubs:{
    UiButton:{props:['disabled','type'],template:'<button :disabled="disabled" :type="type"><slot/></button>'},
    UiInput:{props:['modelValue','type'],emits:['update:modelValue'],template:
      '<input :type="type" :value="modelValue" @input="$emit(&quot;update:modelValue&quot;, $event.target.value)" />'},
    UiDialog:{props:['open'],template:'<section v-if="open" role="dialog"><slot/></section>'},
  }}});wrappers.push(wrapper);return wrapper
}
async function click(wrapper:ReturnType<typeof page>,label:string){await wrapper.findAll('button').find(b=>b.text()===label)!.trigger('click');await flushPromises()}
async function createForm(wrapper:ReturnType<typeof page>){
  await click(wrapper,'创建账号');const inputs=wrapper.find('[role=dialog]').findAll('input')
  await inputs[0]!.setValue('new-fixture');await inputs[1]!.setValue('synthetic-only-password')
}
it('account component reuses remount within five seconds, but manual refresh and expiry read anew',async()=>{
  vi.useFakeTimers();const load=vi.spyOn(managementApi,'accounts').mockResolvedValue([row()])
  page();await flushPromises();wrappers.pop()!.unmount();await vi.advanceTimersByTimeAsync(5000)
  const returned=page();await flushPromises();expect(returned.text()).toContain('fixture-account');expect(load).toHaveBeenCalledOnce()
  await click(returned,'刷新账号列表');expect(load).toHaveBeenCalledTimes(2)
  wrappers.pop()!.unmount();await vi.advanceTimersByTimeAsync(10001);page();await flushPromises();expect(load).toHaveBeenCalledTimes(3)
})
it('local search does not reload accounts or retain its filter across navigation',async()=>{
  const load=vi.spyOn(managementApi,'accounts').mockResolvedValue([row()]);const first=page();await flushPromises()
  await first.find('input').setValue('no-match');expect(first.findAll('article')).toHaveLength(0);expect(load).toHaveBeenCalledOnce()
  wrappers.pop()!.unmount();const second=page();await flushPromises();expect(second.findAll('article')).toHaveLength(1);expect(load).toHaveBeenCalledOnce()
})
it('leaving aborts a pending account read and late response cannot populate a return',async()=>{
  let resolve!:(value:AccountRecord[])=>void,signal!:AbortSignal
  const load=vi.spyOn(managementApi,'accounts').mockImplementationOnce(s=>{signal=s!;return new Promise(r=>{resolve=r})}).mockResolvedValue([{...row(),username:'fresh'}])
  page();await flushPromises();wrappers.pop()!.unmount();expect(signal.aborted).toBe(true)
  resolve([row()]);await flushPromises();const returned=page();await flushPromises();expect(returned.text()).toContain('fresh');expect(load).toHaveBeenCalledTimes(2)
})
it('scope revocation erases account display and forces a fresh list on reentry',async()=>{
  const load=vi.spyOn(managementApi,'accounts').mockResolvedValue([row()]);const first=page();await flushPromises()
  projectScope.clear();await flushPromises();expect(first.findAll('article')).toHaveLength(0)
  wrappers.pop()!.unmount();page();await flushPromises();expect(load).toHaveBeenCalledTimes(2)
})
it('different identities never reuse an account list',async()=>{
  const load=vi.spyOn(managementApi,'accounts').mockResolvedValue([row()]);page();await flushPromises();wrappers.pop()!.unmount()
  useSessionStore().user!.accountId='another-admin';page();await flushPromises();expect(load).toHaveBeenCalledTimes(2)
})
it.each([409,503])('failed create %s clears password, blocks replay and needs an authoritative refresh',async status=>{
  const load=vi.spyOn(managementApi,'accounts').mockResolvedValue([row()]),write=vi.spyOn(managementApi,'createAccount').mockRejectedValue(new ApiError({status}))
  const wrapper=page();await flushPromises();await createForm(wrapper);await wrapper.find('form').trigger('submit');await flushPromises()
  expect((wrapper.find('input[type=password]').element as HTMLInputElement).value).toBe('')
  expect(wrapper.text()).toContain('不会自动重试');await wrapper.find('form').trigger('submit');await flushPromises();expect(write).toHaveBeenCalledOnce()
  await click(wrapper,'取消');await click(wrapper,'刷新账号列表');expect(load).toHaveBeenCalledTimes(2)
  await createForm(wrapper);await click(wrapper,'取消');await click(wrapper,'创建账号');expect((wrapper.find('input[type=password]').element as HTMLInputElement).value).toBe('')
})
it('successful create refreshes list and only read DTOs enter the account cache',async()=>{
  const created={...row(),accountId:'new',username:'new-fixture'}
  const load=vi.spyOn(managementApi,'accounts').mockResolvedValueOnce([row()]).mockResolvedValue([row(),created])
  vi.spyOn(managementApi,'createAccount').mockResolvedValue({...created,password:'response-must-not-be-cached'} as AccountRecord)
  const wrapper=page();await flushPromises();await createForm(wrapper);await wrapper.find('form').trigger('submit');await flushPromises()
  expect(wrapper.find('[role=dialog]').exists()).toBe(false);expect(load).toHaveBeenCalledTimes(2)
  const fallback=vi.fn().mockRejectedValue(new Error('cache should be ready'))
  const cached=await managementReads.read(useManagementReadContext('platform')(),'platform-accounts','',fallback,new AbortController().signal)
  expect(cached).toEqual([row(),created]);expect(fallback).not.toHaveBeenCalled()
  await click(wrapper,'创建账号');expect((wrapper.find('input[type=password]').element as HTMLInputElement).value).toBe('')
})
it('current account edits still revalidate permissions before any following list load',async()=>{
  vi.spyOn(managementApi,'accounts').mockResolvedValue([{...row(),accountId:'admin'}])
  const revalidate=vi.spyOn(useProjectsStore(),'revalidate').mockImplementation(async()=>{projectScope.clear();return false})
  const edit=vi.spyOn(managementApi,'editAccount').mockResolvedValue(row())
  const wrapper=page();await flushPromises();await click(wrapper,'管理账号');await wrapper.find('form').trigger('submit');await flushPromises()
  expect(edit).toHaveBeenCalledOnce();expect(revalidate).toHaveBeenCalledWith(true);expect(wrapper.findAll('article')).toHaveLength(0)
})
it.each([200,409,503])('account write %s invalidates all dependent list tags before and after completion',async status=>{
  let finish!:(r:Response)=>void
  const fetcher=vi.fn(()=>new Promise<Response>(r=>{finish=r})),client=new ApiClient(fetcher),load=vi.fn().mockResolvedValue([row()])
  const tags=['platform-accounts','platform-projects','members'],signal=new AbortController().signal
  for(const tag of tags)await managementReads.read('context',tag,'',load,signal)
  const pending=client.request('/platform/accounts/other',{method:'PATCH',json:{enabled:false,expectedRevision:1}}).catch(e=>e)
  for(const tag of tags)await managementReads.read('context',tag,'',load,signal)
  expect(load).toHaveBeenCalledTimes(6);finish(new Response('{}',{status}));await pending
  for(const tag of tags)await managementReads.read('context',tag,'',load,signal)
  expect(load).toHaveBeenCalledTimes(9);expect(fetcher).toHaveBeenCalledOnce()
})
