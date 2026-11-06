import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { alertsApi } from '../src/features/alerts/api'
import {
  alertSubject, alertTitle, dispositionPresentation, eventFactSeverity, eventPriority,
  formatTimestampUs, matchesOriginFilter, originLabel, alertSceneLabel, alertModelLabel, alertSourceSummary,
} from '../src/features/alerts/presenters'
import { useAlertsStore } from '../src/features/alerts/store'
import type { AlertEvent } from '../src/features/alerts/types'

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

const majorEvent: AlertEvent = {
  eventId: 'mobile:camera:PPE_NO_HELMET:1',
  label: '未佩戴安全帽',
  ruleId: 'PPE_NO_HELMET',
  sourceId: 'camera:back',
  subjectKey: 'track:7',
  severity: 'MAJOR',
  notifySeverity: 'CRITICAL',
  confirmedAtUs: 1_750_000_123_456_789,
  disposition: { status: 'OPEN' },
  evidence: { snapshotUri: '/private/path.jpg' },
}

describe('alert presentation semantics', () => {
  it('uses historical readable provenance, never uploaded IDs or source hashes as names', () => {
    const event: AlertEvent = { ...majorEvent, origin: 'MOBILE_CAMERA', sourceId: 'scene-camera:hash',
      provenance: { kind: 'SCENE', scene: { sceneId: 's2', name: '场景02', revision: 3 },
        plan: { planId: 'p1', name: '联合相机方案' }, memberId: 'm1',
        model: { modelId: 'uploaded-06abc', name: '安全帽', version: '2.0.0' } } }
    expect(alertSceneLabel(event)).toBe('场景02')
    expect(alertModelLabel(event)).toBe('安全帽 · 2.0.0')
    expect(alertSourceSummary(event)).toBe('移动端相机 · 场景02 · 安全帽 · 2.0.0')
    expect(alertSceneLabel({ eventId: 'old' })).toBe('未记录场景')
    expect(alertModelLabel({ eventId: 'old', model: { modelId: 'uploaded-06abc' } })).toBe('未记录模型名称')
    expect(alertSceneLabel({ ...event, provenance: { kind: 'STANDALONE', model: event.provenance!.model } })).toBe('独立模型（无场景）')
  })
  it('keeps fact severity separate from escalated notification priority', () => {
    expect(eventFactSeverity(majorEvent)).toMatchObject({ key: 'important', label: '重要' })
    expect(eventPriority(majorEvent)).toMatchObject({ key: 'critical', label: '严重' })
  })

  it('preserves six-digit microsecond precision in displayed business time', () => {
    expect(formatTimestampUs(1_750_000_123_456_789)).toMatch(/\.456789$/)
    expect(formatTimestampUs(undefined)).toBe('时间未知')
  })

  it('labels known alert origins and groups mobile origins for filtering', () => {
    expect(originLabel('SERVER_STREAM')).toBe('视频流告警')
    expect(originLabel('MOBILE_CAMERA')).toBe('移动端相机')
    expect(originLabel('MOBILE_IMAGE')).toBe('移动端图片')
    expect(originLabel('SERVER_CAMERA')).toBe('来源未标记')
    expect(originLabel(undefined)).toBe('来源未标记')
    expect(matchesOriginFilter('SERVER_STREAM', 'SERVER_STREAM')).toBe(true)
    expect(matchesOriginFilter('MOBILE_IMAGE', 'SERVER_STREAM')).toBe(false)
    expect(matchesOriginFilter('MOBILE_CAMERA', 'MOBILE')).toBe(true)
    expect(matchesOriginFilter('MOBILE_IMAGE', 'MOBILE')).toBe(true)
    expect(matchesOriginFilter(undefined, 'MOBILE')).toBe(false)
    expect(matchesOriginFilter(undefined, 'all')).toBe(true)
  })

  it('uses stable fallbacks for titles, subjects and disposition', () => {
    expect(alertTitle(majorEvent)).toBe('未佩戴安全帽')
    expect(alertSubject({ eventId: 'evt', detectionResults: [{ label: 'person' }] })).toBe('person')
    expect(dispositionPresentation({ status: 'FALSE_POSITIVE' })).toMatchObject({ label: '误报', tone: 'false-positive' })
  })
})

describe('alert API contract', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('encodes real event IDs in detail and disposition paths', async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(majorEvent))
    vi.stubGlobal('fetch', fetch)
    await alertsApi.get(majorEvent.eventId)
    await alertsApi.disposition(majorEvent.eventId, 'FALSE_POSITIVE', '现场复查')
    expect(String(fetch.mock.calls[0][0])).toContain('/alerts/mobile%3Acamera%3APPE_NO_HELMET%3A1')
    expect(String(fetch.mock.calls[1][0])).toContain('/false-positive')
    expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({ note: '现场复查' })
  })

  it('rejects malformed list events instead of rendering invented fallbacks', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ events: [{ label: 'missing id' }] })))
    await expect(alertsApi.list()).rejects.toMatchObject({ code: 'invalid_alert_event' })
  })

  it('carries CAS revision and an independent original request identity', async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json(majorEvent))
    vi.stubGlobal('fetch', fetch)
    await alertsApi.disposition(majorEvent.eventId, 'ACKNOWLEDGED', '', 7)
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ expectedRevision: 7 })
    const id = crypto.randomUUID()
    await alertsApi.requestOriginal(majorEvent.eventId, 7, id)
    expect(String(fetch.mock.calls[1][0])).toContain('/original-requests')
    expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({ expectedRevision: 7, operationId: id })
    expect(new Headers(fetch.mock.calls[1][1]?.headers).get('Idempotency-Key')).toBe(id)
  })

  it('loads evidence as a blob through the authenticated event endpoint', async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(new Blob(['image']), { headers: { 'Content-Type': 'image/jpeg' } }))
    vi.stubGlobal('fetch', fetch)
    const evidence = await alertsApi.evidence(majorEvent.eventId)
    expect(evidence.size).toBe(5)
    expect(String(fetch.mock.calls[0][0])).toContain('/evidence')
  })

  it('generates advice only through an explicit idempotent POST and reads history separately', async () => {
    const generation = { generationId: 'g-1', status: 'NO_MATCH', references: [] }
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => json(init?.method === 'POST' ? generation : { generations: [generation] }))
    vi.stubGlobal('fetch', fetch)
    const operationId = crypto.randomUUID()
    await alertsApi.generateAdvice(majorEvent.eventId, operationId)
    expect(String(fetch.mock.calls[0][0])).toContain('/advice-generations')
    expect(fetch.mock.calls[0][1]?.method).toBe('POST')
    expect(new Headers(fetch.mock.calls[0][1]?.headers).get('Idempotency-Key')).toBe(operationId)
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({})
    await alertsApi.adviceHistory(majorEvent.eventId)
    expect(fetch.mock.calls[1][1]?.method).toBe('GET')
  })
})

describe('alert store', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.unstubAllGlobals())

  it('sorts fetched alerts and loads event detail without a review-status request', async () => {
    const older = { ...majorEvent, eventId: 'older', confirmedAtUs: 100 }
    const newer = { ...majorEvent, eventId: 'newer', confirmedAtUs: 200 }
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/alerts')) return json({ events: [older, newer] })
      return json({ ...newer, state: 'CONFIRMED' })
    })
    vi.stubGlobal('fetch', fetchMock)
    const store = useAlertsStore()
    await store.refresh()
    expect(store.events.map((event) => event.eventId)).toEqual(['newer', 'older'])
    await store.openDetail('newer')
    expect(store.detailPhase).toBe('ready')
    expect(store.selected?.state).toBe('CONFIRMED')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls.every(([input]) => !String(input).includes('/verification'))).toBe(true)
  })

  it('shows list API failure without substituting mock rows', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: { code: 'alerts_unavailable', message: 'database unavailable' } }, 503)))
    const store = useAlertsStore()
    await store.refresh()
    expect(store.phase).toBe('error')
    expect(store.events).toEqual([])
    expect(store.error).toContain('database unavailable')
  })

  it('merges concurrent websocket facts without resetting a recorded disposition', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ events: [{ ...majorEvent, disposition: { status: 'ACKNOWLEDGED', actor: 'admin' } }] })))
    const store = useAlertsStore()
    await store.refresh()
    expect(store.acceptRealtime({ type: 'alert', event: { eventId: majorEvent.eventId, state: 'ENDED', lastSeenAtUs: 300 } })).toBe(true)
    expect(store.events[0].state).toBe('ENDED')
    expect(store.events[0].disposition?.status).toBe('ACKNOWLEDGED')
    expect(store.acceptRealtime({ type: 'heartbeat' })).toBe(false)
  })
})
