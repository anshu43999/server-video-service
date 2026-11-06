import type { AlertDisposition, AlertEvent, AlertSeverityKey } from './types'

export interface SeverityPresentation { key: AlertSeverityKey; label: string; rank: number }

export function severityPresentation(value: unknown): SeverityPresentation {
  const normalized = String(value ?? 'MINOR').trim().toUpperCase()
  if (['CRITICAL', '严重', '重大'].includes(normalized)) return { key: 'critical', label: '严重', rank: 3 }
  if (['MAJOR', 'IMPORTANT', '重要'].includes(normalized)) return { key: 'important', label: '重要', rank: 2 }
  return { key: 'normal', label: '一般', rank: 1 }
}

export function eventPriority(event: AlertEvent) {
  return severityPresentation(event.notifySeverity ?? event.severity)
}

export function eventFactSeverity(event: AlertEvent) {
  return severityPresentation(event.severity)
}

export function alertTitle(event: AlertEvent) {
  return String(event.displayName || event.label || event.ruleId || event.eventId || '未命名告警')
}

export function alertSubject(event: AlertEvent) {
  const first = Array.isArray(event.detectionResults) ? event.detectionResults[0] : undefined
  const detected = first && typeof first === 'object' ? first as Record<string, unknown> : undefined
  return String(event.subjectKey || detected?.label || detected?.className || '未记录主体')
}

export function eventTimestampUs(event: AlertEvent): number | undefined {
  const value = Number(event.confirmedAtUs ?? event.startedAtUs)
  return Number.isSafeInteger(value) && value >= 0 ? value : undefined
}

export function formatTimestampUs(value: unknown): string {
  const microseconds = Number(value)
  if (!Number.isSafeInteger(microseconds) || microseconds < 0) return '时间未知'
  const date = new Date(Math.floor(microseconds / 1000))
  if (Number.isNaN(date.getTime())) return '时间未知'
  const base = new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date)
  return `${base}.${String(microseconds % 1_000_000).padStart(6, '0')}`
}

export function dispositionPresentation(disposition?: AlertDisposition) {
  const value = String(disposition?.status ?? 'OPEN').toUpperCase()
  const labels: Record<string, string> = { OPEN: '待确认', ACKNOWLEDGED: '已确认', FALSE_POSITIVE: '误报', CLOSED: '已关闭' }
  return { value, label: labels[value] ?? value, tone: value === 'OPEN' ? 'pending' : value === 'FALSE_POSITIVE' ? 'false-positive' : 'done' }
}


export function originLabel(origin: unknown) {
  const labels: Record<string, string> = {
    MOBILE_CAMERA: '移动端相机',
    MOBILE_IMAGE: '移动端图片',
    SERVER_STREAM: '视频流告警',
  }
  return labels[String(origin ?? '').trim().toUpperCase()] ?? '来源未标记'
}

export type AlertOriginFilter = 'all' | 'SERVER_STREAM' | 'MOBILE'

export function matchesOriginFilter(origin: unknown, filter: AlertOriginFilter) {
  if (filter === 'all') return true
  const value = String(origin ?? '').trim().toUpperCase()
  if (filter === 'SERVER_STREAM') return value === 'SERVER_STREAM'
  return value === 'MOBILE_CAMERA' || value === 'MOBILE_IMAGE'
}

export function hasEvidence(event: AlertEvent) {
  return Boolean(event.evidence && Object.keys(event.evidence).length)
}

export function alertSceneLabel(event: AlertEvent) {
  if (event.provenance?.kind === 'STANDALONE') return '独立模型（无场景）'
  return event.provenance?.scene?.name || '未记录场景'
}

export function alertModelLabel(event: AlertEvent) {
  const model = event.provenance?.model || event.model
  const name = model?.name || ('modelName' in (model || {}) ? event.model?.modelName : undefined)
  return name ? `${name}${model?.version ? ` · ${model.version}` : ''}` : '未记录模型名称'
}

export function alertSourceSummary(event: AlertEvent) {
  return `${originLabel(event.origin)} · ${alertSceneLabel(event)} · ${alertModelLabel(event)}`
}
