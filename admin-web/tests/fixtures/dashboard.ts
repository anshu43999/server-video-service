import type { DashboardStats, StatsRange } from '../../src/features/dashboard/types'
export function statsFixture(range: StatsRange = 'today', total = 12): DashboardStats {
  return {
    range, from: '2026-10-09T00:00:00Z', to: '2026-10-09T04:00:00Z', generatedAt: '2026-10-09T04:00:00Z', dataSource: 'sqlite',
    summary: { totalEvents: total, severeAlerts: total ? 3 : 0, handledEvents: total ? 6 : 0, resolutionRate: total ? 50 : 0, averageResponseMinutes: total ? 2.5 : null },
    trend: Array.from({ length: range === 'today' ? 12 : range === '7d' ? 7 : 6 }, (_, index) => ({ label: range === 'today' ? `${String(index * 2).padStart(2, '0')}:00` : `10-${String(index + 1).padStart(2, '0')}`, count: total && index === 1 ? total : 0, severe: total && index === 1 ? 3 : 0 })),
    categories: total ? [{ label: '未戴安全帽', count: total, percent: 100 }] : [],
    streams: { total: 1, online: 1, waiting: 0, errors: 0 },
    system: { cpu_percent: 0, memory_percent: 34.2, memory_mb: 125.8, disk_percent: 22.1, gpu: null },
    dispositions: total ? { OPEN: 6, ACKNOWLEDGED: 6 } : {}, severity: { total: total ? { CRITICAL: 3, MINOR: 9 } : {}, handled: total ? { MINOR: 6 } : {} },
  }
}
