import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../src/api/client'
import { conversionApi, modelsApi } from '../src/features/models/api'
import type { ParameterProfile } from '../src/features/models/types'
import { removalOutcome } from '../src/features/models/lifecycle'
const json = (value: unknown) => new Response(JSON.stringify(value), {headers:{'Content-Type':'application/json'}})
afterEach(() => vi.unstubAllGlobals())
describe('model asset contracts', () => {
  it('distinguishes retired versions with pending files from completed physical cleanup', () => {
    const result={uninstalled:true,deletedFiles:2,missingFiles:0,retainedSharedFiles:1,cleanupFailures:[],operationId:'operation-1',revision:2}
    expect(removalOutcome(result)).toEqual({pending:false,text:'模型版本已卸载：回收 2 个文件，保留 1 个共享文件，0 个文件原已缺失。'})
    const partial=removalOutcome({...result,cleanupFailures:['private-path.pt']})
    expect(partial.pending).toBe(true);expect(partial.text).toContain('并非全部文件已回收');expect(partial.text).not.toContain('private-path.pt')
    expect(()=>removalOutcome({...result,deletedFiles:-1})).toThrow('结果待核实')
  })
  it('does not repost legacy alias fields returned beside v2 alert parameters', async () => {
    const fetch = vi.fn(async (_path: unknown, _options?: RequestInit) => json({}))
    vi.stubGlobal('fetch', fetch)
    const alert = { rawLabel:'head', displayName:'未戴安全帽', eventCode:'PPE_NO_HELMET', operator:'PRESENCE', enabled:true, severity:'MAJOR', image:{minimumConfidence:.55,cooldownMs:60000}, camera:{minimumConfidence:.55,cooldownMs:60000,minimumConsecutiveFrames:4,minimumDwellTimeMs:800}, minimumConfidence:.55, minimumConsecutiveFrames:4, unexpectedAlias:'response-only' }
    await modelsApi.saveParameters('helmet','android',{schemaVersion:2,revision:1,detection:{confidenceThreshold:.35,iouThreshold:.45,maxDetections:100},alertRules:[alert]} as unknown as ParameterProfile)
    const rule = JSON.parse(String(fetch.mock.calls[0]?.[1]?.body)).alertRules[0]
    expect(rule).not.toHaveProperty('unexpectedAlias'); expect(rule).not.toHaveProperty('minimumConsecutiveFrames'); expect(rule.camera.minimumConsecutiveFrames).toBe(4)
  })
  it('preserves optimistic revisions and platform without posting response-only fields', async () => {
    const fetch = vi.fn(async (_path: unknown, _options: unknown) => json({}))
    vi.stubGlobal('fetch', fetch)
    await modelsApi.saveParameters('helmet/01','server',{modelId:'helmet/01',modelVersion:'2',platform:'server',source:'custom',schemaVersion:2,revision:7,detection:{confidenceThreshold:.35,iouThreshold:.45,maxDetections:100},alertRules:[],audit:[]} as ParameterProfile)
    expect(fetch.mock.calls[0]?.[0]).toBe('/aiyoloapi/models/helmet%2F01/parameters?platform=server')
    const request = (fetch.mock.calls[0] as unknown as [string, RequestInit])[1]
    expect(JSON.parse(String(request.body))).toEqual({schemaVersion:2,expectedRevision:7,detection:{confidenceThreshold:.35,iouThreshold:.45,maxDetections:100},alertRules:[]})
  })
  it('targets the requested asset version for uninstall and freezes calibration by ID', async () => {
    const fetch = vi.fn(async (_path: unknown, _options: unknown) => json({}))
    vi.stubGlobal('fetch',fetch)
    await modelsApi.remove('helmet','1.0',3,'request-1')
    const deletion=fetch.mock.calls[0]?.[1] as RequestInit
    const headers=new Headers(deletion.headers)
    expect(headers.get('If-Match')).toBe('"3"');expect(headers.get('Idempotency-Key')).toBe('request-1')
    expect(deletion.body).toBeUndefined()
    await conversionApi.mobile('upload/01','dataset/01')
    expect(fetch.mock.calls.map(call => call[0])).toEqual(['/aiyoloapi/models/helmet/versions/1.0','/aiyoloapi/conversion/uploads/upload%2F01/mobile?calibrationDatasetId=dataset%2F01'])
  })
  it('rejects malformed lists and redacts full logs without truncating them to error length', async () => {
    vi.stubGlobal('fetch',vi.fn(async () => json({models:{}})))
    await expect(modelsApi.list()).rejects.toMatchObject({kind:'invalid-response'})
    vi.stubGlobal('fetch',vi.fn(async () => new Response('Bearer secret-token\n' + 'x'.repeat(1000))))
    const log = await conversionApi.log('job')
    expect(log).toContain('[REDACTED]'); expect(log).not.toContain('secret-token'); expect(log.length).toBeGreaterThan(1000)
  })
})
class FakeXhr {
  static last: FakeXhr
  status=202; responseText='{"job":{"id":"job"}}'; timeout=0; upload={onprogress:null as any}
  onload: any; onabort: any; onerror: any; ontimeout: any
  path=''; body: unknown; headers: Record<string,string>={}
  constructor() { FakeXhr.last=this }
  open(_method: string,path: string) {this.path=path}
  setRequestHeader(key: string,value: string) {this.headers[key]=value}
  getResponseHeader() {return null}
  send(body: unknown) {this.body=body}
  abort() {this.onabort?.()}
}
describe('byte upload lifecycle', () => {
  it('uses raw bytes and real transport progress, including unknown lengths', async () => {
    vi.stubGlobal('XMLHttpRequest',FakeXhr)
    const client=new ApiClient(), progress=vi.fn(), file=new Blob(['binary'])
    const promise=client.uploadWithProgress('/conversion/uploads',file,{query:{name:'现场模型',filename:'train.pt'},onProgress:progress})
    const xhr=FakeXhr.last
    expect(xhr.body).toBe(file); expect(xhr.headers['Content-Type']).toBe('application/octet-stream')
    expect(xhr.path).toContain('filename=train.pt')
    xhr.upload.onprogress({lengthComputable:true,loaded:5,total:10})
    xhr.upload.onprogress({lengthComputable:false})
    expect(progress.mock.calls).toEqual([[50],[null]])
    await xhr.onload(); await expect(promise).resolves.toEqual({job:{id:'job'}})
  })
  it('retains shared permission semantics for XHR and rejects oversize with a safe message', async () => {
    vi.stubGlobal('XMLHttpRequest',FakeXhr)
    const client=new ApiClient(); client.setUnauthorizedHandler(async () => 'active')
    const denied=client.uploadWithProgress('/conversion/uploads',new Blob(['x']))
    const result=expect(denied).rejects.toMatchObject({status:403,code:'permission_denied'})
    FakeXhr.last.status=401; FakeXhr.last.responseText='{"detail":"denied"}'; await FakeXhr.last.onload(); await result
    const oversize=client.uploadWithProgress('/conversion/uploads',new Blob(['x']))
    const expected=expect(oversize).rejects.toMatchObject({status:413})
    FakeXhr.last.status=413; await FakeXhr.last.onload(); await expected
  })
  it('cancels on caller abort and refuses already cancelled uploads', async () => {
    vi.stubGlobal('XMLHttpRequest',FakeXhr)
    const controller=new AbortController(), client=new ApiClient()
    const promise=client.uploadWithProgress('/conversion/uploads',new Blob(['x']),{signal:controller.signal})
    const result=expect(promise).rejects.toMatchObject({kind:'cancelled'})
    controller.abort(); await result
    await expect(client.uploadWithProgress('/conversion/uploads',new Blob(['x']),{signal:controller.signal})).rejects.toMatchObject({kind:'cancelled'})
  })
})
