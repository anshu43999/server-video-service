import { apiClient } from '../../api/client'
import { ApiError } from '../../api/errors'
import type { AdviceGeneration, AlertEvent, AlertsResponse, DispositionAction } from './types'

function eventPath(eventId: string, suffix = '') {
  return `/alerts/${encodeURIComponent(eventId)}${suffix}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function parseEvent(value: unknown): AlertEvent {
  if (!isRecord(value) || typeof value.eventId !== 'string' || !value.eventId.trim()) {
    throw new ApiError({ kind: 'invalid-response', code: 'invalid_alert_event', message: '服务返回了无效的告警事件' })
  }
  return value as AlertEvent
}

function parseList(value: unknown): AlertsResponse {
  if (!isRecord(value) || !Array.isArray(value.events)) {
    throw new ApiError({ kind: 'invalid-response', code: 'invalid_alert_list', message: '服务返回了无效的告警列表' })
  }
  return { events: value.events.map(parseEvent) }
}

export const alertsApi = {
  async list(signal?: AbortSignal) { return parseList(await apiClient.request<unknown>('/alerts', { signal })) },
  async recent(signal?: AbortSignal) { return parseList(await apiClient.request<unknown>('/alerts', { signal, query: { limit: 20 } })) },
  async get(eventId: string) { return parseEvent(await apiClient.request<unknown>(eventPath(eventId))) },
  evidence(eventId: string, signal?: AbortSignal) {
    return apiClient.request<Blob>(eventPath(eventId, '/evidence'), { response: 'blob', signal, timeoutMs: 20_000 })
  },
  requestOriginal(eventId: string, expectedRevision: number, operationId: string) {
    return apiClient.request<AlertEvent>(eventPath(eventId, '/original-requests'), {
      method: 'POST', json: { operationId, expectedRevision }, headers: { 'Idempotency-Key': operationId },
    }).then(parseEvent)
  },
  latestAdvice(eventId: string, signal?: AbortSignal) {
    return apiClient.request<AdviceGeneration>(eventPath(eventId, '/advice-generations/latest'), { signal })
  },
  adviceHistory(eventId: string, signal?: AbortSignal) {
    return apiClient.request<{ generations: AdviceGeneration[] }>(eventPath(eventId, '/advice-generations'), { signal })
  },
  generateAdvice(eventId: string, operationId: string, retryOfGenerationId?: string) {
    return apiClient.request<AdviceGeneration>(eventPath(eventId, '/advice-generations'), {
      method: 'POST', json: retryOfGenerationId ? { retryOfGenerationId } : {},
      headers: { 'Idempotency-Key': operationId }, timeoutMs: 30_000,
    })
  },
  originalEvidence(eventId: string, version: number, signal?: AbortSignal) {
    return apiClient.request<Blob>(eventPath(eventId, `/evidence/original/${version}`), {
      response: 'blob', signal, timeoutMs: 20_000,
    })
  },
  disposition(eventId: string, action: DispositionAction, note?: string, expectedRevision?: number) {
    const endpoint = action === 'ACKNOWLEDGED' ? '/acknowledge' : '/false-positive'
    return apiClient.request<AlertEvent>(eventPath(eventId, endpoint), {
      method: 'POST', json: { note: note?.trim() || undefined, ...(expectedRevision === undefined ? {} : { expectedRevision }) },
    }).then(parseEvent)
  },
  exportAlerts() {
    return apiClient.request<Blob>('/alerts/export', { response: 'blob', timeoutMs: 120_000 })
  },
  exportFalsePositives() {
    return apiClient.request<Blob>('/alerts/false-positives/export', { response: 'blob', timeoutMs: 120_000 })
  },
}
