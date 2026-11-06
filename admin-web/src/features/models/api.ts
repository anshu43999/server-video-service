import { apiClient } from '../../api/client'
import { removalHeaders, type RemovalImpact, type ModelRemovalResult } from './lifecycle'
import { ApiError, redactMessage } from '../../api/errors'
import type { CalibrationDataset, ConversionConfig, ConversionJob, ConversionSettings, ModelAsset, ModelTarget, ParameterProfile, Platform } from './types'
const modelPath = (id: string) => `/models/${encodeURIComponent(id)}`
function list<T>(value: T[] | undefined, name: string): T[] {
  if (!Array.isArray(value)) throw new ApiError({ kind: 'invalid-response', message: `${name}响应无效` })
  return value
}
export const modelsApi = {
  async list(signal?: AbortSignal) { return list((await apiClient.request<{ models: ModelAsset[] }>('/models', { signal })).models, '模型目录') },
  detail(id: string, version: string, signal?: AbortSignal) { return apiClient.request<ModelAsset>(`${modelPath(id)}/versions/${encodeURIComponent(version)}`, { signal }) },
  activate(id: string) { return apiClient.request<{ active_model: ModelAsset }>(`${modelPath(id)}/activate`, { method: 'POST' }) },
  impact(id:string,version:string,signal?:AbortSignal){return apiClient.request<RemovalImpact>(`${modelPath(id)}/versions/${encodeURIComponent(version)}/removal-impact`,{signal})},
  remove(id: string, version: string,revision:number,key:string) { return apiClient.request<ModelRemovalResult>(`${modelPath(id)}/versions/${encodeURIComponent(version)}`, { method: 'DELETE',headers:removalHeaders(revision,key) }) },
  publish(model:ModelAsset, targets:ModelTarget[], reason:string) { return apiClient.request<ModelAsset>(`${modelPath(model.modelId)}/versions/${encodeURIComponent(model.version)}/publish`, {method:'POST',json:{targets,licenseApproved:true,reason}}) },
  validatePcRuntime(model:ModelAsset) { return apiClient.request<ModelAsset>(`${modelPath(model.modelId)}/versions/${encodeURIComponent(model.version)}/validate-pc-runtime`, {method:'POST',timeoutMs:300_000}) },
  register(manifest: string) { return apiClient.request('/models/register', { method: 'POST', json: { manifest_path: manifest } }) },
  parameters(id: string, platform: Platform, signal?: AbortSignal, version?: string) { return apiClient.request<ParameterProfile>(`${modelPath(id)}/parameters`, { query: { platform, version }, signal }) },
  saveParameters(id: string, platform: Platform, profile: ParameterProfile, version?: string) {
    const alertRules = profile.alertRules.map(({ rawLabel, displayName, eventCode, operator, enabled, severity, image, camera }) => ({ rawLabel, displayName, eventCode, operator, enabled, severity, image, camera }))
    return apiClient.request<ParameterProfile>(`${modelPath(id)}/parameters`, { method: 'PUT', query: { platform, version }, json: { schemaVersion: 2, expectedRevision: profile.revision, detection: profile.detection, alertRules } })
  },
  resetParameters(id: string, platform: Platform, expectedRevision: number, version?: string) { return apiClient.request<ParameterProfile>(`${modelPath(id)}/parameters`, { method: 'DELETE', query: { platform, version, expectedRevision } }) },
  async download(model: ModelAsset, artifactId: string) {
    const blob = await apiClient.request<Blob>(`${modelPath(model.modelId)}/versions/${encodeURIComponent(model.version)}/artifacts/${encodeURIComponent(artifactId)}/download`, { response: 'blob', timeoutMs: 300_000 })
    saveBlob(blob, `${model.modelId}-${model.version}-${artifactId}.${model.artifacts?.find(item => item.artifactId === artifactId)?.format ?? 'bin'}`)
  },
}
export const conversionApi = {
  config(signal?: AbortSignal) { return apiClient.request<ConversionSettings>('/conversion/config', { signal }) },
  configure(config: ConversionConfig) { return apiClient.request<{ config: ConversionConfig }>('/conversion/config', { method: 'PUT', json: config }) },
  check() { return apiClient.request<ConversionJob>('/conversion/check', { method: 'POST' }) },
  async jobs(signal?: AbortSignal) { return list((await apiClient.request<{ jobs: ConversionJob[] }>('/conversion/jobs', { signal })).jobs, '转换任务') },
  retry(id: string) { return apiClient.request<ConversionJob>(`/conversion/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' }) },
  mobile(uploadId: string, calibrationId: string) { return apiClient.request<ConversionJob>(`/conversion/uploads/${encodeURIComponent(uploadId)}/mobile`, { method: 'POST', query: { calibrationDatasetId: calibrationId } }) },
  async log(id: string) { return redactMessage(await apiClient.request<string>(`/conversion/jobs/${encodeURIComponent(id)}/log`, { response: 'text' }), '暂无日志', 32_000) },
  async datasets(signal?: AbortSignal) { const value = await apiClient.request<{ datasets: CalibrationDataset[]; max_upload_bytes: number }>('/conversion/calibration-datasets', { signal }); return { ...value, datasets: list(value.datasets, '校准集') } },
  dataset(id: string, signal?: AbortSignal) { return apiClient.request<CalibrationDataset>(`/conversion/calibration-datasets/${encodeURIComponent(id)}`, { signal }) },
  removeDataset(id: string) { return apiClient.request(`/conversion/calibration-datasets/${encodeURIComponent(id)}`, { method: 'DELETE' }) },
  upload(file: File, metadata: { name: string; version: string; scenario: string; modelId?: string; supportedTargets?:ModelTarget[] }, signal: AbortSignal, onProgress: (value: number | null) => void) {
    return apiClient.uploadWithProgress<{ upload_id: string; model_id: string; job: ConversionJob }>('/conversion/uploads', file, { query: { ...metadata, filename: file.name }, signal, onProgress })
  },
  uploadDataset(file: File, metadata: { name: string; version: string; scenario: string }, signal: AbortSignal, onProgress: (value: number | null) => void) {
    return apiClient.uploadWithProgress<CalibrationDataset>('/conversion/calibration-datasets', file, { query: { ...metadata, filename: file.name }, signal, onProgress })
  },
}
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename.replace(/[\\/:*?"<>|]/g, '_')
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function formatBytes(bytes?: number) { return typeof bytes === 'number' ? `${(bytes / 1048576).toFixed(1)} MB` : '未知大小' }
export function errorText(error: unknown) { return error instanceof Error ? redactMessage(error.message) : '请求失败' }
