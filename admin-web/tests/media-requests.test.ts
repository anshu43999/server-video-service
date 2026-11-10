// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { useVisibleElement } from '../src/api/useVisibleElement'
import { EvidenceRequests, evidenceRequests } from '../src/features/alerts/evidenceRequests'
import EvidenceThumbnail from '../src/features/alerts/EvidenceThumbnail.vue'
import { alertsApi } from '../src/features/alerts/api'
import { projectScope } from '../src/api/projectScope'
import { AdminPreview } from '../src/features/streams/preview'

afterEach(()=>{evidenceRequests.clear();projectScope.clear();projectScope.enabled=false;vi.useRealTimers();vi.restoreAllMocks();vi.unstubAllGlobals()})
const gate=<T>()=>{let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>{resolve=r});return{promise,resolve}}
const jpeg=()=>new Response('frame',{headers:{'Content-Type':'image/jpeg'}})

it('limits evidence to three unsettled transports and removes queued cancelled reads',async()=>{
  const queue=new EvidenceRequests(),gates=Array.from({length:5},()=>gate<number>()),controllers=gates.map(()=>new AbortController())
  const load=vi.fn((index:number)=>gates[index]!.promise)
  const reads=gates.map((_,i)=>queue.run(()=>load(i),controllers[i]!.signal).catch(e=>e))
  await flushPromises();expect(load).toHaveBeenCalledTimes(3)
  controllers[3]!.abort();controllers[0]!.abort();await flushPromises()
  expect(load).toHaveBeenCalledTimes(3);expect((await reads[0]).kind).toBe('cancelled')
  gates[0]!.resolve(0);await flushPromises();expect(load.mock.calls.map(c=>c[0])).toEqual([0,1,2,4])
  for(let i=1;i<5;i++)gates[i]!.resolve(i)
  await Promise.all(reads);expect((await reads[3]).kind).toBe('cancelled')
})
it('scope clear cancels queued and in-flight media and rejects late responses',async()=>{
  projectScope.enable();const pending=gate<Blob>(),load=vi.fn(()=>pending.promise)
  const reads=Array.from({length:4},()=>evidenceRequests.run(load,new AbortController().signal).catch(e=>e))
  await flushPromises();projectScope.clear();for(const read of reads)expect((await read).kind).toBe('cancelled')
  pending.resolve(new Blob(['late']));await flushPromises();expect(load).toHaveBeenCalledTimes(3)
})
it('thumbnail reads only on intersection, cancels hidden, keys revisions and releases URLs',async()=>{
  let observer!:IntersectionObserverCallback,target!:Element
  vi.stubGlobal('IntersectionObserver',class{constructor(cb:IntersectionObserverCallback){observer=cb}observe(el:Element){target=el}disconnect(){}})
  const visible=(value:boolean)=>observer([{target,isIntersecting:value} as IntersectionObserverEntry],{} as IntersectionObserver)
  const delayed=gate<Blob>(),signals:AbortSignal[]=[]
  const load=vi.spyOn(alertsApi,'evidence').mockImplementationOnce((_id,signal)=>{signals.push(signal!);return delayed.promise}).mockResolvedValue(new Blob(['new']))
  const create=vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:new'),revoke=vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>{})
  const event={projectId:'a',eventId:'e',evidence:{thumbnail:{contentVersion:1}}}
  const view=mount(EvidenceThumbnail,{props:{event}});await flushPromises();expect(load).not.toHaveBeenCalled()
  visible(true);await flushPromises();expect(load).toHaveBeenCalledOnce()
  visible(false);await flushPromises();expect(signals[0]?.aborted).toBe(true)
  delayed.resolve(new Blob(['old']));await flushPromises();expect(create).not.toHaveBeenCalled()
  visible(true);await flushPromises();expect(view.find('img').exists()).toBe(true)
  await view.setProps({event:{...event,evidence:{thumbnail:{contentVersion:2}}}});await flushPromises();expect(load).toHaveBeenCalledTimes(3)
  expect(revoke).toHaveBeenCalledWith('blob:new');view.unmount()
})
it('backs off no-frame and transient errors to five seconds, then resets on a valid frame',async()=>{
  vi.useFakeTimers();const fetch=vi.fn().mockResolvedValue(new Response(null,{status:204})),status=vi.fn()
  const preview=new AdminPreview({fetchImpl:fetch,onFrame:()=>{},onStatus:status,createObjectURL:()=> 'blob:ok',revokeObjectURL:()=>{}})
  preview.start('/aiyoloapi/streams/a/preview?connection=1');await flushPromises();expect(fetch).toHaveBeenCalledTimes(1)
  for(const [i,delay]of [500,1000,2000,5000].entries()){await vi.advanceTimersByTimeAsync(delay-1);expect(fetch).toHaveBeenCalledTimes(i+1);await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(fetch).toHaveBeenCalledTimes(i+2)}
  fetch.mockImplementation(jpeg);await vi.advanceTimersByTimeAsync(5000);await flushPromises();expect(status).toHaveBeenLastCalledWith('open')
  const count=fetch.mock.calls.length;await vi.advanceTimersByTimeAsync(200);await flushPromises();expect(fetch).toHaveBeenCalledTimes(count+1)
  fetch.mockRejectedValue(new Error('offline'));await vi.advanceTimersByTimeAsync(200);await flushPromises()
  const failed=fetch.mock.calls.length;await vi.advanceTimersByTimeAsync(499);expect(fetch).toHaveBeenCalledTimes(failed);await vi.advanceTimersByTimeAsync(1);expect(fetch).toHaveBeenCalledTimes(failed+1);preview.stop()
})
it('waits for image decode and clears a stalled picture without fetching discarded frames',async()=>{
  vi.useFakeTimers();const fetch=vi.fn().mockImplementation(jpeg),frame=vi.fn(),status=vi.fn(),revoke=vi.fn()
  const preview=new AdminPreview({fetchImpl:fetch,onFrame:frame,onStatus:status,waitForFrameLoad:true,createObjectURL:()=> 'blob:decode',revokeObjectURL:revoke})
  preview.start('/aiyoloapi/streams/a/preview?connection=1');await flushPromises()
  await vi.advanceTimersByTimeAsync(4999);expect(fetch).toHaveBeenCalledOnce();expect(status).not.toHaveBeenCalledWith('open')
  await vi.advanceTimersByTimeAsync(1);expect(frame).toHaveBeenLastCalledWith('');expect(revoke).toHaveBeenCalledWith('blob:decode')
  await vi.advanceTimersByTimeAsync(500);await flushPromises();expect(fetch).toHaveBeenCalledTimes(2)
  preview.frameLoaded();await vi.advanceTimersByTimeAsync(199);expect(fetch).toHaveBeenCalledTimes(2);await vi.advanceTimersByTimeAsync(1);expect(fetch).toHaveBeenCalledTimes(3);preview.stop()
})
it('hide/resume and project switch stay single-flight when old transport ignores cancellation',async()=>{
  vi.useFakeTimers();projectScope.enable();projectScope.enter('a')
  const pending=gate<Response>(),signals:AbortSignal[]=[],frame=vi.fn()
  const fetch=vi.fn((_path:unknown,init?:RequestInit)=>{signals.push(init?.signal as AbortSignal);return signals.length===1?pending.promise:Promise.resolve(jpeg())})
  const preview=new AdminPreview({fetchImpl:fetch,onFrame:frame,createObjectURL:()=> 'blob:fresh',revokeObjectURL:()=>{}})
  preview.start('/aiyoloapi/streams/gate/preview?connection=1');await flushPromises();preview.setVisible(false)
  expect(signals[0]?.aborted).toBe(true);preview.setVisible(true);preview.setVisible(true);expect(fetch).toHaveBeenCalledOnce()
  projectScope.clear();projectScope.enter('b');preview.start('/aiyoloapi/streams/gate/preview?connection=2');expect(fetch).toHaveBeenCalledOnce()
  pending.resolve(jpeg());await flushPromises();expect(fetch).toHaveBeenCalledTimes(2);expect(frame).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[1]?.[0]).toContain('/projects/b/');preview.stop();await vi.advanceTimersByTimeAsync(10000);expect(fetch).toHaveBeenCalledTimes(2)
})
it('tab hiding clears decoded frames and resumes only one fresh read',async()=>{
  vi.useFakeTimers();let hidden=false;vi.spyOn(document,'visibilityState','get').mockImplementation(()=>hidden?'hidden':'visible')
  const fetch=vi.fn().mockImplementation(jpeg),frame=vi.fn()
  const preview=new AdminPreview({fetchImpl:fetch,onFrame:frame,createObjectURL:()=> 'blob:frame',revokeObjectURL:()=>{}})
  preview.start('/aiyoloapi/streams/a/preview?connection=1');await flushPromises();hidden=true;document.dispatchEvent(new Event('visibilitychange'))
  expect(frame).toHaveBeenLastCalledWith('');await vi.advanceTimersByTimeAsync(10000);expect(fetch).toHaveBeenCalledOnce()
  hidden=false;document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('online'));await flushPromises();expect(fetch).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(100);window.dispatchEvent(new Event('online'));document.dispatchEvent(new Event('visibilitychange'));await flushPromises()
  expect(fetch).toHaveBeenCalledTimes(2);await vi.advanceTimersByTimeAsync(100);expect(fetch).toHaveBeenCalledTimes(3);preview.stop()
})
it('ignores obsolete intersection notifications after replacement and unmount',async()=>{
  const observers:{callback:IntersectionObserverCallback,target?:Element}[]=[]
  vi.stubGlobal('IntersectionObserver',class{
    entry:{callback:IntersectionObserverCallback,target?:Element}
    constructor(callback:IntersectionObserverCallback){this.entry={callback};observers.push(this.entry)}
    observe(target:Element){this.entry.target=target}
    disconnect(){}
  })
  let target=ref<HTMLElement>(),visible=ref(false)
  const view=mount(defineComponent({setup(){visible=useVisibleElement(target);return()=>null}}))
  target.value=document.createElement('span');await flushPromises();const old=observers.at(-1)!
  target.value=document.createElement('span');await flushPromises();const current=observers.at(-1)!
  const notify=(entry:typeof current,value:boolean)=>entry.callback([{target:entry.target,isIntersecting:value} as IntersectionObserverEntry],{} as IntersectionObserver)
  notify(old,true);expect(visible.value).toBe(false)
  notify(current,true);expect(visible.value).toBe(true)
  view.unmount();notify(current,false);expect(visible.value).toBe(true)
})
it('clears timed-out pictures and backs off even when a transport ignores abort',async()=>{
  vi.useFakeTimers();const pending=gate<Response>(),frame=vi.fn(),status=vi.fn()
  let signal:AbortSignal|undefined
  const fetch=vi.fn((_path:unknown,init?:RequestInit)=>Promise.resolve(jpeg()))
    .mockImplementationOnce(()=>Promise.resolve(jpeg()))
    .mockImplementationOnce((_path,init)=>{signal=init?.signal as AbortSignal;return pending.promise})
  const preview=new AdminPreview({fetchImpl:fetch,onFrame:frame,onStatus:status,createObjectURL:()=> 'blob:frame',revokeObjectURL:()=>{}})
  preview.start('/aiyoloapi/streams/a/preview?connection=1');await flushPromises()
  await vi.advanceTimersByTimeAsync(200);await vi.advanceTimersByTimeAsync(5000)
  expect(signal?.aborted).toBe(true);expect(frame).toHaveBeenLastCalledWith('');expect(status).toHaveBeenLastCalledWith('error','Preview timeout')
  await vi.advanceTimersByTimeAsync(10000);expect(fetch).toHaveBeenCalledTimes(2)
  pending.resolve(jpeg());await flushPromises();expect(frame).toHaveBeenLastCalledWith('')
  await vi.advanceTimersByTimeAsync(499);expect(fetch).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(fetch).toHaveBeenCalledTimes(3);preview.stop()
})
