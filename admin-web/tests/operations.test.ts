import { afterEach, expect, it, vi } from 'vitest'
import { operationsApi, type Rule } from '../src/features/operations/api'
import { projectScope } from '../src/api/projectScope'
const rule:Rule={ruleId:'helmet',name:'安全帽',ruleVersion:2,enabled:true,subjectKind:'track',operator:'PRESENCE',requires:['BOX'],targetLabels:['head'],thresholds:{minimumConfidence:.5}}
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}})
afterEach(()=>{vi.unstubAllGlobals();projectScope.clear();projectScope.enabled=false})
it('sends the read revision in one atomic write and surfaces conflicts without replay',async()=>{
  const fetch=vi.fn(async (_path:unknown,_options?:RequestInit)=>json({detail:'revision conflict'},409));vi.stubGlobal('fetch',fetch)
  await expect(operationsApi.saveRule(rule,rule)).rejects.toMatchObject({status:409})
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toMatchObject({expectedRevision:2})
  expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).not.toHaveProperty('ruleVersion')
})
it('scopes create, binding, unbinding and delete with their expected revisions',async()=>{
  projectScope.enable();projectScope.enter('project-a')
  const fetch=vi.fn(async (_path:unknown,_options?:RequestInit)=>json({}));vi.stubGlobal('fetch',fetch)
  await operationsApi.saveRule(rule)
  await operationsApi.bind('helmet',{sourceId:'gate',capabilities:['BOX']},3)
  await operationsApi.unbind('helmet','gate',4)
  await operationsApi.removeRule('helmet',5)
  expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body)).expectedRevision).toBe(0)
  expect(JSON.parse(String(fetch.mock.calls[1]?.[1]?.body)).expectedRevision).toBe(3)
  expect(fetch.mock.calls.map(c=>c[0])).toEqual(['/aiyoloapi/projects/project-a/rules','/aiyoloapi/projects/project-a/rules/helmet/bindings','/aiyoloapi/projects/project-a/rules/helmet/bindings/gate?expectedRevision=4','/aiyoloapi/projects/project-a/rules/helmet?expectedRevision=5'])
})
it('saves and resets only project policy fields; diagnostics uses explicit project metrics',async()=>{
  projectScope.enable();projectScope.enter('a')
  const fetch=vi.fn(async (_path:unknown,_options?:RequestInit)=>json({}));vi.stubGlobal('fetch',fetch)
  await operationsApi.savePolicy({revision:3,enabled:true,channels:['app'],minimumSeverity:'MAJOR'})
  await operationsApi.resetPolicy(4);await operationsApi.projectMetrics()
  expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual({enabled:true,channels:['app'],minimumSeverity:'MAJOR',expectedRevision:3})
  expect(fetch.mock.calls[2]?.[0]).toBe('/aiyoloapi/projects/a/metrics')
  projectScope.clear()
  await expect(operationsApi.projectMetrics()).rejects.toMatchObject({kind:'cancelled'})
})
it('treats non-2xx platform health as unavailable',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>json({status:'degraded'},503)))
  await expect(operationsApi.health()).rejects.toMatchObject({status:503})
})

it.each([
  ['/admin', '/healthz'],
  ['/admin/diagnostics', '/healthz'],
  ['/admin-next/diagnostics', '/healthz'],
  ['/video/admin', '/video/healthz'],
  ['/video/admin/diagnostics', '/video/healthz'],
  ['/video/admin-next/diagnostics', '/video/healthz'],
  ['/videos/admin/diagnostics', '/healthz'],
  ['/video/administrator', '/healthz'],
])('routes health from %s without moving business APIs', async (pathname, healthPath) => {
  vi.stubGlobal('location', { pathname })
  projectScope.enable()
  const fetch = vi.fn(async (_path: unknown, _options?: RequestInit) => json({ status: 'ok' }))
  vi.stubGlobal('fetch', fetch)
  await operationsApi.health()
  await operationsApi.metrics()
  projectScope.enter('project-a')
  await operationsApi.projectMetrics()
  expect(fetch.mock.calls.map(call => call[0])).toEqual([
    healthPath, '/aiyoloapi/metrics', '/aiyoloapi/projects/project-a/metrics',
  ])
  expect(fetch.mock.calls[0]?.[1]?.credentials).toBe('same-origin')
})

it.each([404, 503])('preserves real health errors under /video: %i', async status => {
  vi.stubGlobal('location', { pathname: '/video/admin/diagnostics' })
  const fetch = vi.fn(async (_path: unknown) => json({ status: 'degraded' }, status))
  vi.stubGlobal('fetch', fetch)
  await expect(operationsApi.health()).rejects.toMatchObject({ kind: 'http', status })
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0]?.[0]).toBe('/video/healthz')
})

it('keeps menu-leave cancellation distinct from failure for prefixed health', async () => {
  vi.stubGlobal('location', { pathname: '/video/admin/diagnostics' })
  const fetch = vi.fn((_path: unknown, options?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    options?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
  }))
  vi.stubGlobal('fetch', fetch)
  const controller = new AbortController()
  const pending = expect(operationsApi.health(controller.signal)).rejects.toMatchObject({ kind: 'cancelled', code: 'request_cancelled' })
  controller.abort()
  await pending
  expect(fetch.mock.calls[0]?.[0]).toBe('/video/healthz')
})
