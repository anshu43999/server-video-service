export type StatsRange = 'today' | '7d' | '30d'
export interface DashboardStats {
  range: StatsRange
  from: string
  to: string
  generatedAt: string
  dataSource: string
  summary: { totalEvents: number; severeAlerts: number; handledEvents: number; resolutionRate: number; averageResponseMinutes: number | null }
  trend: { label: string; count: number; severe: number }[]
  categories: { label: string; count: number; percent: number }[]
  streams: { total: number; online: number; waiting: number; errors: number }
  system: {
    cpu_percent: number | null; memory_percent: number | null; memory_mb: number | null; disk_percent: number | null
    gpu: { utilization_percent: number | null; memory_used_mb: number | null; memory_total_mb: number | null }[] | null
  }
  dispositions: Record<string, number>
  severity: { total: Record<string, number>; handled: Record<string, number> }
}
