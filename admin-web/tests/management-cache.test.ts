// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { managementReads, ReadCache } from '../src/api/readCache'
import { ApiClient } from '../src/api/client'
import { ApiError } from '../src/api/errors'
import { projectScope } from '../src/api/projectScope'
import { useManagement } from '../src/features/management/useManagement'
import { useManagementReadContext } from '../src/features/management/readContext'
import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { useSessionStore } from '../src/stores/session'
import { useProjectsStore } from '../src/stores/projects'
const signal = () => new AbortController().signal
const deferred = <T>() => { let resolve!: (v:T)=>void; return { promise: new Promise<T>(r=>{resolve=r}), resolve:(v:T)=>resolve(v) } }
const wrappers: ReturnType<typeof mount>[] = []
afterEach(()=>{wrappers.splice(0).forEach(w=>w.unmount());managementReads.invalidate();projectScope.clear();projectScope.enabled=false;vi.useRealTimers();vi.restoreAllMocks()})
function setup(load:(s:AbortSignal)=>Promise<string[]>, context=ref('alice/platform/r1'), tag='platform-projects') {
  let state!:ReturnType<typeof useManagement<string[]>>
  wrappers.push(mount(defineComponent({setup(){ state=useManagement<string[]>([],load,{context:()=>context.value,tag});return()=>null }})))
  return state
}
it('reuses list on remount before TTL, clones data and forces manual refresh',async()=>{
  vi.useFakeTimers();const load=vi.fn().mockResolvedValue(['one'])
  const a=setup(load);await a.loadInitial();a.data.value.push('local');wrappers.pop()!.unmount()
  await vi.advanceTimersByTimeAsync(5000)
  const b=setup(load);await b.loadInitial();expect(b.data.value).toEqual(['one']);expect(load).toHaveBeenCalledOnce()
  await b.refresh();expect(load).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(10000);await b.loadInitial();expect(load).toHaveBeenCalledTimes(3)
})
it('coalesces same list reads and repeated refresh with no extra concurrent loader',async()=>{
  const gate=deferred<string[]>(),load=vi.fn(()=>gate.promise),a=setup(load),b=setup(load)
  const reads=[a.loadInitial(),b.loadInitial(),a.loadInitial()]
  await flushPromises();expect(load).toHaveBeenCalledOnce();gate.resolve(['shared']);await Promise.all(reads)
  const next=deferred<string[]>();load.mockReturnValue(next.promise)
  const refreshes=[a.refresh(),a.refresh()];await flushPromises();expect(load).toHaveBeenCalledTimes(2)
  next.resolve(['fresh']);await Promise.all(refreshes);expect(a.data.value).toEqual(['fresh'])
})
it('scope clear immediately erases data and pending consumers without reviving late results',async()=>{
  const gate=deferred<string[]>();let underlying!:AbortSignal
  const a=setup(s=>{underlying=s;return gate.promise}),pending=a.loadInitial()
  await flushPromises();projectScope.clear();expect(underlying.aborted).toBe(true)
  gate.resolve(['old']);await pending;expect(a.data.value).toEqual([]);expect(a.error.value).toBe('')
})
it('unmount cancels last consumer while another consumer remains valid',async()=>{
  const gate=deferred<string[]>();let underlying!:AbortSignal
  const load=(s:AbortSignal)=>{underlying=s;return gate.promise},a=setup(load),b=setup(load)
  const reads=[a.loadInitial(),b.loadInitial()];await flushPromises()
  wrappers.shift()!.unmount();expect(underlying.aborted).toBe(false)
  gate.resolve(['shared']);await Promise.all(reads);expect(a.data.value).toEqual([]);expect(b.data.value).toEqual(['shared'])
})
it('identity and permission revision change clears old display and loads fresh',async()=>{
  const context=ref('alice/a/r1'),load=vi.fn().mockResolvedValue(['private']),a=setup(load,context,'members')
  await a.loadInitial();const gate=deferred<string[]>();load.mockReturnValue(gate.promise)
  context.value='alice/a/r2';expect(a.data.value).toEqual([]);await flushPromises()
  gate.resolve(['latest']);await flushPromises();expect(a.data.value).toEqual(['latest']);expect(load).toHaveBeenCalledTimes(2)
})
it('write cancels pre-write list and reloads authoritative result without reusing snapshot',async()=>{
  const gate=deferred<string[]>(),load=vi.fn().mockReturnValueOnce(gate.promise).mockResolvedValue(['post-write']),a=setup(load)
  const reading=a.loadInitial();await flushPromises();const action=vi.fn().mockResolvedValue({})
  await a.run(action,()=>{});gate.resolve(['old']);await reading
  expect(a.data.value).toEqual(['post-write']);expect(action).toHaveBeenCalledOnce();expect(load).toHaveBeenCalledTimes(2)
})
it('failed writes require a fresh successful read and never replay automatically',async()=>{
  const load=vi.fn().mockResolvedValue(['one']),a=setup(load);await a.loadInitial()
  const action=vi.fn().mockRejectedValue(new ApiError({status:409,code:'revision_conflict'}))
  await a.run(action,()=>{});await a.run(action,()=>{});expect(action).toHaveBeenCalledOnce();expect(a.needsReload.value).toBe(true)
  load.mockRejectedValueOnce(new Error('offline'));await a.refresh();expect(a.needsReload.value).toBe(true)
  await a.refresh();expect(a.needsReload.value).toBe(false);expect(load).toHaveBeenCalledTimes(3)
})
it('a failed write during a pending refresh releases loading for manual recovery',async()=>{
  const gate=deferred<string[]>(),load=vi.fn().mockResolvedValueOnce(['old']).mockReturnValueOnce(gate.promise).mockResolvedValue(['new']),a=setup(load)
  await a.loadInitial();const pending=a.refresh();await flushPromises();expect(a.loading.value).toBe(true)
  await a.run(async()=>{throw new ApiError({status:503})},()=>{})
  expect(a.loading.value).toBe(false);expect(a.needsReload.value).toBe(true)
  gate.resolve(['stale']);await pending;await a.refresh();expect(a.data.value).toEqual(['new'])
})
it.each(['network','timeout','cancelled'])('uncertain management %s transport clears snapshots and never repeats writes',async kind=>{
  vi.useFakeTimers();const load=vi.fn().mockResolvedValue([]),abort=new AbortController()
  const fetcher=vi.fn((_url:RequestInfo|URL,options?:RequestInit)=>new Promise<Response>((_resolve,reject)=>{
    options?.signal?.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')))
    if(kind==='network')reject(new TypeError('offline'))
  })),client=new ApiClient(fetcher)
  await managementReads.read('a','members','',load,signal())
  const pending=client.request('/platform/accounts/a',{method:'PATCH',signal:abort.signal,timeoutMs:100}).catch(e=>e)
  if(kind==='timeout')await vi.advanceTimersByTimeAsync(100)
  if(kind==='cancelled')abort.abort()
  expect(await pending).toMatchObject({kind})
  await managementReads.read('a','members','',load,signal());expect(load).toHaveBeenCalledTimes(2);expect(fetcher).toHaveBeenCalledOnce()
})
it.each([200,409,503])('actual management write %s invalidates before and after, never replays',async status=>{
  for(const path of ['/platform/projects/p','platform/accounts/a','projects/p/members/a','projects/p/transfer-owner']) {
    const load=vi.fn().mockResolvedValue([]),gate=deferred<Response>(),fetcher=vi.fn(()=>gate.promise),client=new ApiClient(fetcher)
    for(const tag of ['members','platform-projects'])await managementReads.read('a',tag,'',load,signal())
    const write=client.request(path.startsWith('/')?path:'/'+path,{method:'PATCH',json:{}}).catch(e=>e)
    for(const tag of ['members','platform-projects'])await managementReads.read('a',tag,'',load,signal())
    expect(load).toHaveBeenCalledTimes(4);gate.resolve(new Response('{}',{status}));await write
    for(const tag of ['members','platform-projects'])await managementReads.read('a',tag,'',load,signal())
    expect(load).toHaveBeenCalledTimes(6);expect(fetcher).toHaveBeenCalledOnce();managementReads.invalidate()
  }
})
it('unrelated writes retain management snapshots',async()=>{
  const load=vi.fn().mockResolvedValue([]),client=new ApiClient(vi.fn(async()=>new Response('{}')))
  await managementReads.read('a','members','',load,signal());await client.request('/alerts/e/acknowledge',{method:'POST'})
  await managementReads.read('a','members','',load,signal());expect(load).toHaveBeenCalledOnce()
})
it('cached promise rejects same-turn cancellation or invalidation',async()=>{
  const cache=new ReadCache(),load=async()=>['private']
  await cache.read('a','members','',load,signal());const abort=new AbortController()
  const pending=cache.read('a','members','',load,abort.signal);abort.abort()
  await expect(pending).rejects.toMatchObject({kind:'cancelled'})
  const stale=cache.read('a','members','',load,signal());cache.invalidate()
  await expect(stale).rejects.toMatchObject({kind:'cancelled'})
})
it('actual context keys partition account, role, project and permission snapshots',()=>{
  const pinia=createPinia();setActivePinia(pinia)
  try {
    const session=useSessionStore(),projects=useProjectsStore()
    session.user={accountId:'alice',username:'fixture',role:'admin',platformRole:'PLATFORM_ADMIN',contractVersion:'m33-v1'}
    session.phase='authenticated'
    const platform=useManagementReadContext('platform'),project=useManagementReadContext('project')
    const original=platform();expect(project()).not.toBe(original)
    session.user={...session.user};expect(platform()).toBe(original)
    session.user.accountId='bob';expect(platform()).not.toBe(original)
    const bob=platform();session.user.platformRole='NORMAL_USER';expect(platform()).not.toBe(bob)
    projects.current={projectId:'a',projectCode:'a',displayName:'A',lifecycleState:'ACTIVE',revision:1,membershipRevision:1,projectRole:'PROJECT_OWNER',platformEntry:false,capabilities:['project.read']}
    const a=project();projects.current.membershipRevision=2;expect(project()).not.toBe(a)
    const revision=project();projects.current.capabilities=[];expect(project()).not.toBe(revision)
    const permission=project();projects.current.projectId='b';expect(project()).not.toBe(permission)
    const before=platform();projects.projects=[{...projects.current}];expect(platform()).not.toBe(before)
  } finally {disposePinia(pinia)}
})
