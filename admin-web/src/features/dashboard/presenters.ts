import type { StreamItem } from '../streams/types'
export function streamStatus(stream: StreamItem) {
  if (stream.enabled === false || stream.configuration_state === 'disabled' || stream.runtime_state === 'disabled') return { key: 'disabled', label: '已停用' }
  if (stream.last_error || stream.model_error || stream.runtime_state === 'error') return { key: 'error', label: '运行异常' }
  if (stream.runtime_available !== true) return { key: 'waiting', label: '未运行' }
  if ((stream.received_fps ?? 0) > 0 || stream.publish_state === 'connected') return { key: 'online', label: '运行中' }
  return { key: 'waiting', label: '等待画面' }
}
export function canPreview(stream: StreamItem) {
  return stream.runtime_available === true && stream.enabled !== false && stream.configuration_state !== 'disabled' && stream.runtime_state !== 'disabled'
}
export function percent(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '不可用' }
export function amount(value: unknown, unit: string) { return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)} ${unit}` : '不可用' }
