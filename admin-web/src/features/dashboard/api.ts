import { apiClient } from '../../api/client'
import { ApiError } from '../../api/errors'
import type { DashboardStats, StatsRange } from './types'

function invalid(): never {
  throw new ApiError({ kind: 'invalid-response', code: 'invalid_dashboard_stats', message: '统计响应无效，当前指标不可用' })
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid()
  return value as Record<string, unknown>
}
function count(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return invalid()
  return value
}
function text(value: unknown): string { return typeof value === 'string' ? value : invalid() }
function metric(value: unknown): number | null { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null }
function counts(value: unknown): Record<string, number> { return Object.fromEntries(Object.entries(record(value)).map(([key, value]) => [key, count(value)])) }
function rows<T>(value: unknown, parse: (row: Record<string, unknown>) => T): T[] {
  return Array.isArray(value) ? value.map(row => parse(record(row))) : invalid()
}
export function parseStats(value: unknown, range: StatsRange): DashboardStats {
  const data = record(value), summary = record(data.summary), streams = record(data.streams), system = record(data.system)
  const severity = record(data.severity)
  if (data.range !== range) return invalid()
  return {
    range, from: text(data.from), to: text(data.to), generatedAt: text(data.generatedAt), dataSource: text(data.dataSource),
    summary: { totalEvents: count(summary.totalEvents), severeAlerts: count(summary.severeAlerts), handledEvents: count(summary.handledEvents), resolutionRate: count(summary.resolutionRate), averageResponseMinutes: summary.averageResponseMinutes === null ? null : count(summary.averageResponseMinutes) },
    trend: rows(data.trend, row => ({ label: text(row.label), count: count(row.count), severe: count(row.severe) })),
    categories: rows(data.categories, row => ({ label: text(row.label), count: count(row.count), percent: count(row.percent) })),
    streams: { total: count(streams.total), online: count(streams.online), waiting: count(streams.waiting), errors: count(streams.errors) },
    system: { cpu_percent: metric(system.cpu_percent), memory_percent: metric(system.memory_percent), memory_mb: metric(system.memory_mb), disk_percent: metric(system.disk_percent), gpu: Array.isArray(system.gpu) ? rows(system.gpu, row => ({ utilization_percent: metric(row.utilization_percent), memory_used_mb: metric(row.memory_used_mb), memory_total_mb: metric(row.memory_total_mb) })) : null },
    dispositions: counts(data.dispositions), severity: { total: counts(severity.total), handled: counts(severity.handled) },
  }
}
export const dashboardApi = {
  async stats(range: StatsRange, signal?: AbortSignal) {
    return parseStats(await apiClient.request<unknown>('/dashboard/stats', { query: { range }, signal }), range)
  },
}
