import { afterEach, expect, it, vi } from 'vitest'
import { ReadCache, dashboardReads, invalidateDashboardWrite } from '../src/api/readCache'
import { projectScope } from '../src/api/projectScope'
import { ApiClient } from '../src/api/client'
const signal = () => new AbortController().signal
const deferred = <T>() => { let resolve!: (value:T)=>void; return {promise:new Promise<T>(r=>{resolve=r}),resolve:(value:T)=>resolve(value)} }
afterEach(()=>{dashboardReads.invalidate();projectScope.clear();projectScope.enabled=false;vi.useRealTimers();vi.restoreAllMocks();vi.unstubAllGlobals()})

it('coalesces identical queries, clones values and expires after ten seconds',async()=>{
  vi.useFakeTimers();const cache=new ReadCache(),load=vi.fn().mockResolvedValue({items:[1]})
  const [a,b]=await Promise.all([cache.read('alice/project-a/r1','stats','today',load,signal()),cache.read('alice/project-a/r1','stats','today',load,signal())])
  expect(load).toHaveBeenCalledOnce();(a as {items:number[]}).items.push(2)
  expect(b).toEqual({items:[1]})
  await vi.advanceTimersByTimeAsync(9999);expect(await cache.read('alice/project-a/r1','stats','today',load,signal())).toEqual({items:[1]})
  expect(load).toHaveBeenCalledOnce();await vi.advanceTimersByTimeAsync(1)
  await cache.read('alice/project-a/r1','stats','today',load,signal());expect(load).toHaveBeenCalledTimes(2)
})
it('separates identity, platform/project, permission revision and query parameters',async()=>{
  const cache=new ReadCache(),load=vi.fn().mockResolvedValue([])
  for(const context of ['alice/platform/r1','alice/a/r1','alice/b/r1','bob/a/r1','alice/a/r2']) {
    await cache.read(context,'stats','today',load,signal());await cache.read(context,'stats','7d',load,signal())
  }
  expect(load).toHaveBeenCalledTimes(10)
})
it('cancels one consumer without cancelling another then cancels the last consumer',async()=>{
  const cache=new ReadCache(),gate=deferred<number>(),a=new AbortController(),b=new AbortController()
  let underlying!:AbortSignal;const load=vi.fn((s:AbortSignal)=>{underlying=s;return gate.promise})
  const first=cache.read('a','stats','today',load,a.signal).catch(e=>e)
  const second=cache.read('a','stats','today',load,b.signal).catch(e=>e)
  await Promise.resolve();a.abort();expect((await first).kind).toBe('cancelled');expect(underlying.aborted).toBe(false)
  b.abort();expect((await second).kind).toBe('cancelled');expect(underlying.aborted).toBe(true)
  gate.resolve(99);await Promise.resolve()
  expect(await cache.read('a','stats','today',async()=>1,signal())).toBe(1)
})
it('invalidates pending snapshots even when transport ignores cancellation',async()=>{
  const cache=new ReadCache(),gate=deferred<number>()
  const pending=cache.read('a','stats','today',()=>gate.promise,signal()).catch(e=>e)
  await Promise.resolve();cache.invalidate(['stats']);expect((await pending).kind).toBe('cancelled')
  gate.resolve(99);await Promise.resolve()
  expect(await cache.read('a','stats','today',async()=>2,signal())).toBe(2)
})
it('never caches failures and bounds settled entries',async()=>{
  const cache=new ReadCache(10000,2),load=vi.fn().mockRejectedValueOnce(new Error('failed')).mockResolvedValue(1)
  await expect(cache.read('a','stats','today',load,signal())).rejects.toThrow('failed')
  await cache.read('a','stats','today',load,signal());expect(load).toHaveBeenCalledTimes(2)
  await cache.read('b','stats','today',load,signal());await cache.read('c','stats','today',load,signal())
  await cache.read('a','stats','today',load,signal());expect(load).toHaveBeenCalledTimes(5)
})
it('scope clear invalidates all tags; targeted writes retain unrelated sources',async()=>{
  const load=vi.fn().mockResolvedValue([])
  for(const tag of ['stats','recent','streams'])await dashboardReads.read('a',tag,'',load,signal())
  invalidateDashboardWrite('/aiyoloapi/projects/a/alerts/e/acknowledge')
  for(const tag of ['stats','recent','streams'])await dashboardReads.read('a',tag,'',load,signal())
  expect(load).toHaveBeenCalledTimes(5)
  projectScope.clear()
  for(const tag of ['stats','recent','streams'])await dashboardReads.read('a',tag,'',load,signal())
  expect(load).toHaveBeenCalledTimes(8)
})
it.each([200,503])('actual API write status %s invalidates before/after without replay',async status=>{
  const load=vi.fn().mockResolvedValue(1),gate=deferred<Response>(),fetcher=vi.fn(()=>gate.promise)
  const client=new ApiClient(fetcher)
  await dashboardReads.read('a','stats','today',load,signal())
  const write=client.request('/alerts/e/acknowledge',{method:'POST',json:{}}).catch(e=>e)
  await dashboardReads.read('a','stats','today',load,signal());expect(load).toHaveBeenCalledTimes(2)
  gate.resolve(new Response('{}',{status}));await write
  await dashboardReads.read('a','stats','today',load,signal());expect(load).toHaveBeenCalledTimes(3);expect(fetcher).toHaveBeenCalledOnce()
})
it.each([200,503])('XHR model upload status %s invalidates before/after without replay',async status=>{
  class Upload {
    static last:Upload
    status=status;responseText='{}';timeout=0;upload={};onload?:()=>Promise<void>;onabort?:()=>void
    sent=0
    constructor(){Upload.last=this}
    open(){} setRequestHeader(){} getResponseHeader(){return null}
    send(){this.sent++} abort(){this.onabort?.()}
  }
  vi.stubGlobal('XMLHttpRequest',Upload)
  const load=vi.fn().mockResolvedValue(1),client=new ApiClient()
  await dashboardReads.read('a','stats','today',load,signal())
  const write=client.uploadWithProgress('/models',new Blob(['test']),{query:{version:'1'}}).catch(e=>e)
  await dashboardReads.read('a','stats','today',load,signal());expect(load).toHaveBeenCalledTimes(2)
  await Upload.last.onload!();await write
  await dashboardReads.read('a','stats','today',load,signal());expect(load).toHaveBeenCalledTimes(3);expect(Upload.last.sent).toBe(1)
})
