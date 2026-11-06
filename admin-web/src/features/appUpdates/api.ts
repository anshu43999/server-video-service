import { apiClient } from '../../api/client'
import { ApiError, errorFromResponse } from '../../api/errors'
import { projectScope } from '../../api/projectScope'

export const PACKAGE = 'com.aiyolo.inspection' as const
export interface Scope { contractVersion: 'app-update/v1'; publisherId: string; packageName: typeof PACKAGE; channel: string; deploymentId: string }
export interface Configuration { scopes: Scope[]; gateCapabilities: string[]; maxApkBytes: number; uploadEnabled: boolean; externalEnabled: boolean }
export type State = 'pending' | 'verifying' | 'verified' | 'failed' | 'draft' | 'published' | 'stopped' | 'retired'
export interface Result { resourceId: string; state: State; revision: number }
export interface ArtifactDetails { packageName: string; publisherId: string; versionCode: number | null; versionName: string | null; sizeBytes: number | null; sha256: string | null; signerSha256: string | null; minSdk: number | null; abis: string[]; serverContractRange: { min: number | null; max: number | null }; dataSchemaVersion: number | null; readableDataSchemaRange: { min: number | null; max: number | null }; errorCode: string | null; verifiedAt: string | null; jobs?: { jobId: string; kind: string; state: string; errorCode: string | null; resolvedArtifactId: string | null; targetArtifactId: string | null; createdAt: string }[]; createdAt: string }
export interface SourceDetails { artifactId: string; storageMode: 'internal' | 'external'; accessMode: 'public' | 'presigned'; allowedDownloadHosts: string[]; sha256: string; sizeBytes: number; availabilityState: string; createdAt: string }
export interface Binding { releaseId: string; artifactId: string; sourceId: string; sourceRevision: number }
export interface ReleaseDetails extends Omit<Scope, 'contractVersion'> { policyId: string; artifactId: string; importance: 'normal' | 'important'; releasePurpose: 'normal' | 'recovery'; notes: string[]; publishedAt: string | null; stoppedAt: string | null; minSupportedVersionCode: number; restrictedCapabilities: string[]; sourceBinding: Binding | null; createdAt: string }
export interface AuditDetails { actorId: string; action: string; resourceId: string; reason: string; result: string; beforeRevision: number | null; afterRevision: number | null; createdAt: string }
export interface Resource<D> extends Result { resourceType: 'artifact' | 'source' | 'release' | 'audit'; details: D }
export type Artifact = Resource<ArtifactDetails>
export type Source = Resource<SourceDetails>
export type Release = Resource<ReleaseDetails>
export type Audit = Resource<AuditDetails>
export interface Page<T> { items: T[]; nextCursor: string | null }
export interface Mutation { idempotencyKey: string; reason: string }
export interface Draft extends Scope, Mutation { artifactId: string; importance: 'normal' | 'important'; notes: string[] }
export interface Publish extends Scope, Mutation { expectedPolicyRevision: number; releaseId: string; sourceId: string; sourceRevision: number; minSupportedVersionCode: number; restrictedCapabilities: string[] }
export interface Stop extends Scope, Mutation { expectedPolicyRevision: number; releaseId: string }
export interface External extends Mutation { packageName: typeof PACKAGE; downloadUrl: string; allowedDownloadHosts: string[] }
export interface RollbackPlan extends Scope { expectedPolicyRevision: number; affectedReleaseIds: string[]; stableReleaseId: string; recoveryReleaseId: string | null }
export interface RollbackPreview { expectedPolicyRevision: number; previewFingerprint: string; expiresAt: string; ready: boolean; blockers: string[]; contactedDevices: number; affectedDevices: number; recoveryState: 'ready' | 'pending' }
export interface RollbackOperation { operationId: string; status: 'accepted' | 'applied' | 'failed'; effectivePolicyRevision: number | null; recoveryState: 'ready' | 'pending'; deviceCounts: Record<string, number>; lastContactBefore: string | null; errorCode: string | null }
const root = '/admin/app-updates'
const segment = encodeURIComponent

function invalid(): never { throw new ApiError({ kind: 'invalid-response', message: '版本服务响应无效，请刷新后重试' }) }
function result<T extends Result>(value: T): T {
  if (!value || typeof value.resourceId !== 'string' || !value.resourceId || !Number.isInteger(value.revision) || value.revision < 1 || !['pending', 'verifying', 'verified', 'failed', 'draft', 'published', 'stopped', 'retired'].includes(value.state)) invalid()
  return value
}
function resource<T extends Resource<unknown>>(value: T): T {
  result(value)
  if (!value.details || typeof value.details !== 'object') invalid()
  const d = value.details as Record<string, unknown>
  const strings = (v: unknown) => Array.isArray(v) && v.every(s => typeof s === 'string')
  if (value.resourceType === 'artifact') {
    if (!strings(d.abis) || !d.serverContractRange || !d.readableDataSchemaRange || (d.jobs !== undefined && !Array.isArray(d.jobs))) invalid()
  } else if (value.resourceType === 'release') {
    if (!strings(d.notes) || !strings(d.restrictedCapabilities) || typeof d.artifactId !== 'string' || !Number.isInteger(d.minSupportedVersionCode)) invalid()
  } else if (value.resourceType === 'source') {
    if (!strings(d.allowedDownloadHosts) || !['internal', 'external'].includes(String(d.storageMode))) invalid()
  } else if (value.resourceType !== 'audit') invalid()
  return value
}
function page<T extends Resource<unknown>>(value: Page<T>): Page<T> {
  if (!value || !Array.isArray(value.items) || value.items.length > 100 || !(value.nextCursor === null || typeof value.nextCursor === 'string')) invalid()
  return { items: value.items.map(resource), nextCursor: value.nextCursor }
}
function rollbackPreview(value: RollbackPreview) {
  if (!value || !/^[a-f0-9]{64}$/.test(value.previewFingerprint) || !Number.isFinite(Date.parse(value.expiresAt)) || typeof value.ready !== 'boolean' || !Array.isArray(value.blockers) || value.blockers.some(v => typeof v !== 'string') || !Number.isInteger(value.expectedPolicyRevision) || !Number.isSafeInteger(value.contactedDevices) || !Number.isSafeInteger(value.affectedDevices) || value.affectedDevices < 0 || value.contactedDevices < value.affectedDevices || !['ready', 'pending'].includes(value.recoveryState)) invalid()
  return value
}
function rollbackOperation(value: RollbackOperation) {
  if (!value || typeof value.operationId !== 'string' || !['accepted', 'applied', 'failed'].includes(value.status) || !['ready', 'pending'].includes(value.recoveryState) || !value.deviceCounts || Object.values(value.deviceCounts).some(v => !Number.isSafeInteger(v) || v < 0)) invalid()
  return value
}
export const appUpdatesApi = {
  rollbackPreview(body: RollbackPlan, signal?: AbortSignal) { return apiClient.request<RollbackPreview>(root + '/rollback-preview', { method: 'POST', json: body, signal }).then(rollbackPreview) },
  rollback(body: RollbackPlan & Mutation & { previewFingerprint: string }, signal?: AbortSignal) { return apiClient.request<RollbackOperation>(root + '/rollbacks', { method: 'POST', json: body, signal }).then(rollbackOperation) },
  rollbackOperation(id: string, signal?: AbortSignal) { return apiClient.request<RollbackOperation>(root + '/rollbacks/' + segment(id), { signal }).then(rollbackOperation) },
  async configuration(signal?: AbortSignal) {
    const value = await apiClient.request<Configuration>(root + '/configuration', { signal })
    if (!value || !Array.isArray(value.scopes) || !value.scopes.length || !Array.isArray(value.gateCapabilities) || !Number.isSafeInteger(value.maxApkBytes) || value.maxApkBytes < 1 || typeof value.uploadEnabled !== 'boolean' || typeof value.externalEnabled !== 'boolean' || value.scopes.some(s => s.contractVersion !== 'app-update/v1' || s.packageName !== PACKAGE || !s.publisherId || !s.channel || !s.deploymentId)) invalid()
    return value
  },
  list(kind: 'artifacts' | 'releases' | 'audit', cursor?: string | null, signal?: AbortSignal) {
    return apiClient.request<Page<Artifact | Release | Audit>>(root + '/' + kind, { query: { limit: 30, cursor }, signal }).then(page)
  },
  artifact(id: string, signal?: AbortSignal) { return apiClient.request<Artifact>(root + '/artifacts/' + segment(id), { signal }).then(resource) },
  release(id: string, signal?: AbortSignal) { return apiClient.request<Release>(root + '/releases/' + segment(id), { signal }).then(resource) },
  sources(id: string, cursor?: string | null, signal?: AbortSignal) { return apiClient.request<Page<Source>>(root + '/artifacts/' + segment(id) + '/download-sources', { query: { limit: 30, cursor }, signal }).then(page) },
  draft(body: Draft, signal?: AbortSignal) { return apiClient.request<Result>(root + '/releases', { method: 'POST', json: body, signal }).then(result) },
  publish(body: Publish, signal?: AbortSignal) { return apiClient.request<Result>(root + '/releases/' + segment(body.releaseId) + '/publish', { method: 'POST', json: body, signal }).then(result) },
  stop(body: Stop, signal?: AbortSignal) { return apiClient.request<Result>(root + '/releases/' + segment(body.releaseId) + '/stop', { method: 'POST', json: body, signal }).then(result) },
  external(body: External, signal?: AbortSignal) { return apiClient.request<Result>(root + '/external-artifacts', { method: 'POST', json: body, signal }).then(result) },
  addSource(id: string, body: External & { expectedArtifactSha256: string }, signal?: AbortSignal) { return apiClient.request<Result>(root + '/artifacts/' + segment(id) + '/download-sources', { method: 'POST', json: body, signal }).then(result) },
  upload(file: File, mutation: Mutation, options: { signal?: AbortSignal; onProgress?: (percent: number | null) => void } = {}): Promise<Result> {
    // Native XHR is used only for multipart upload progress. Dynamic cookie
    // authentication stays same-origin; no tokens go to the APK source.
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      const generation = projectScope.generation
      let settled = false
      const unregister = projectScope.enabled ? projectScope.register(() => xhr.abort()) : () => {}
      const abort = () => xhr.abort()
      const finish = (error?: unknown, value?: Result) => {
        if (settled) return
        settled = true; unregister(); options.signal?.removeEventListener('abort', abort)
        error ? reject(error) : resolve(value!)
      }
      if (options.signal?.aborted) { finish(new ApiError({ kind: 'cancelled', message: '上传已取消' })); return }
      xhr.open('POST', '/aiyoloapi' + root + '/artifacts/upload')
      xhr.timeout = 310_000
      xhr.upload.onprogress = event => options.onProgress?.(event.lengthComputable ? Math.min(100, event.loaded / event.total * 100) : null)
      xhr.onabort = () => finish(new ApiError({ kind: 'cancelled', message: '上传已中断，请刷新台账确认服务端状态' }))
      xhr.onerror = () => finish(new ApiError({ kind: 'network', message: '连接中断，请刷新台账确认服务端状态' }))
      xhr.ontimeout = () => finish(new ApiError({ kind: 'timeout', message: '上传超时，请刷新台账确认服务端状态' }))
      xhr.onload = () => {
        try {
          projectScope.assertCurrent(generation)
          const value = JSON.parse(xhr.responseText)
          if (xhr.status < 200 || xhr.status >= 300) { finish(errorFromResponse(xhr.status, value, xhr.getResponseHeader('retry-after'))); return }
          finish(undefined, result(value))
        } catch (e) { finish(e instanceof ApiError ? e : new ApiError({ kind: 'invalid-response', message: '上传响应不明确，请刷新台账确认状态' })) }
      }
      options.signal?.addEventListener('abort', abort, { once: true })
      const form = new FormData()
      form.append('idempotencyKey', mutation.idempotencyKey); form.append('reason', mutation.reason); form.append('apk', file)
      xhr.send(form)
    })
  },
}

const messages: Record<string, string> = {
  rollback_preview_stale: '预览已过期或来源、证据发生变化，请重新预览并确认。',
  recovery_incompatible: '恢复方案不满足版本、签名、数据或协议兼容要求，请重新预览检查阻塞项。',
  policy_revision_conflict: '策略已被其他操作修改。请关闭此窗口，刷新台账后重新确认。',
  source_revision_conflict: '下载来源已变化，请关闭此窗口并刷新后重新选择。',
  idempotency_conflict: '本次操作与已登记请求冲突。请刷新核对结果，再发起新操作。',
  compatibility_gate_unreachable: '兼容门槛不可达，请检查目标版本、设备兼容性和受限在线能力。',
  signer_not_approved: 'APK 证书不在批准范围内，不能发布。',
  artifact_not_verified: '安装包尚未通过完整核验，不能发布。',
  source_not_verified: '下载来源尚未通过核验，不能发布。',
  version_not_increasing: '目标版本码必须高于当前活跃版本。',
  release_stopped: '此版本已停止分发，请刷新台账。',
  source_unavailable: '文件源不可用，请检查存储或 HTTPS 下载入口。',
  service_unavailable: '升级服务未配置完整或暂时不可用，请联系平台运维。',
  external_apk_disabled: '第三方 APK 登记尚未启用。',
  apk_upload_disabled: 'APK 上传尚未启用。',
  platform_admin_required: '仅当前启用的平台管理员可管理 App 版本。',
}
export function updateError(error: unknown): string {
  if (!(error instanceof ApiError)) return '操作未完成，请刷新台账确认结果后重试。'
  if (messages[error.code]) return messages[error.code]!
  if (error.kind === 'network' || error.kind === 'timeout') return '连接中断或超时，结果尚未确认。请使用相同内容重试，或刷新台账核对结果。'
  // Never echo server messages which might contain a submitted external URL.
  return error.status === 401 ? '登录已失效，请重新登录。' : error.status === 403 ? '当前账号没有版本管理权限。' : error.status === 429 ? '服务繁忙，请稍后重试。' : error.status === 413 ? 'APK 超过服务允许的大小。' : error.kind === 'cancelled' ? '请求已取消，请刷新确认服务端状态。' : '请求未完成，请检查填写内容或刷新后重试。'
}
export function formatBytes(value: number | null | undefined) { if (value == null) return '待核验'; return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(2)} MB` }
export function parseNotes(text: string) { const notes = text.split(/\r?\n/).map(s => s.trim()).filter(Boolean); if (notes.length > 30 || notes.some(s => s.length > 2000)) throw new Error('更新说明最多 30 条，每条不超过 2000 字。'); return notes }
export function externalFields(url: string, hostsText: string) {
  const hosts = [...new Set(hostsText.split(/[\s,，]+/).map(s => s.trim()).filter(Boolean))]
  const parsed = new URL(url)
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.hash || (parsed.port && parsed.port !== '443') || !hosts.includes(parsed.hostname) || !hosts.length || hosts.length > 16) throw new Error('请填写无凭据的公开 HTTPS 直链，并将下载及重定向域名加入白名单。')
  return { downloadUrl: url, allowedDownloadHosts: hosts }
}
