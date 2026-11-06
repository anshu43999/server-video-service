import { apiClient } from '../../api/client'
import { ApiError } from '../../api/errors'

export type KnowledgeStatus = 'ACTIVE' | 'INACTIVE'
export interface AdviceStep { stepId: string; order: number; title: string; instruction: string }
export interface PolicyReference { referenceId: string; documentTitle: string; documentNumber: string | null; documentVersion: string; chapter: string | null; clauseId: string | null; excerpt: string; sourceName: string; sourceType: 'MOCK_KNOWLEDGE_BASE'; effectiveDate: string | null }
export interface KnowledgePayload { title: string; riskDescription: string; adviceTemplate: { title: string; steps: AdviceStep[]; cautions: string[] }; references: PolicyReference[]; applicability: string; sourceType: 'MOCK_KNOWLEDGE_BASE' }
export interface KnowledgeEntry extends KnowledgePayload { entryId: string; projectId: string; matchKey: { alertTypeId: string; recognitionCategoryId: string }; status: KnowledgeStatus; revision: number; createdBy: string; updatedBy: string; createdAt: string; updatedAt: string; origin?: 'SYSTEM' | 'PROJECT' | 'PROJECT_OVERRIDE'; systemVersion?: number; baseRevision?: number }
export interface KnowledgeRevision { revision: number; action: 'CREATE' | 'UPDATE' | 'ACTIVATE' | 'DEACTIVATE' | 'INHERIT'; actor: string; createdAt: string; snapshot: KnowledgeEntry }
export interface SystemKnowledgeVersion { version: number; catalogRevision: number; notes: string; publishedBy: string; publishedAt: string; entryCount: number }
export interface ProjectKnowledgeBase { version: number; revision: number; versions: SystemKnowledgeVersion[] }
export interface KnowledgeDraft extends KnowledgePayload { entryId: string; alertTypeId: string; recognitionCategoryId: string; status: KnowledgeStatus }

const segment = encodeURIComponent
function assertEntry(value: KnowledgeEntry) {
  if (!value || !value.entryId || !Number.isInteger(value.revision) || !value.matchKey?.alertTypeId || !value.matchKey?.recognitionCategoryId || !Array.isArray(value.references)) throw new ApiError({ kind: 'invalid-response', message: '知识资料响应无效，请刷新核验' })
  return value
}
function knowledgeApi(base: string) { return {
  async list(filters: { status?: KnowledgeStatus; alertTypeId?: string; recognitionCategoryId?: string } = {}, signal?: AbortSignal) {
    const value = await apiClient.request<{ entries: KnowledgeEntry[] }>(base + '/knowledge-entries', { query: filters, signal })
    if (!Array.isArray(value.entries)) throw new ApiError({ kind: 'invalid-response', message: '知识资料列表响应无效' })
    return value.entries.map(assertEntry)
  },
  get(entryId: string, signal?: AbortSignal) { return apiClient.request<KnowledgeEntry>(
    base + '/knowledge-entries/' + segment(entryId), { signal }).then(assertEntry) },
  create(draft: KnowledgeDraft, signal?: AbortSignal) { return apiClient.request<KnowledgeEntry>(base + '/knowledge-entries', { method: 'POST', json: draft, headers: { 'Idempotency-Key': crypto.randomUUID() }, signal }).then(assertEntry) },
  update(entry: KnowledgeEntry, payload: KnowledgePayload, signal?: AbortSignal) { return apiClient.request<KnowledgeEntry>(
    base + '/knowledge-entries/' + segment(entry.entryId), { method: 'PUT', json: { ...payload, expectedRevision: entry.revision }, headers: { 'Idempotency-Key': crypto.randomUUID() }, signal }).then(assertEntry) },
  status(entry: KnowledgeEntry, status: KnowledgeStatus, signal?: AbortSignal) { return apiClient.request<KnowledgeEntry>(
    base + '/knowledge-entries/' + segment(entry.entryId) + '/status', { method: 'POST', json: { status, expectedRevision: entry.revision }, headers: { 'Idempotency-Key': crypto.randomUUID() }, signal }).then(assertEntry) },
  async revisions(entryId: string, signal?: AbortSignal) { const value = await apiClient.request<{ revisions: KnowledgeRevision[] }>(
    base + '/knowledge-entries/' + segment(entryId) + '/revisions', { signal }); if (!Array.isArray(value.revisions)) throw new ApiError({ kind: 'invalid-response', message: '版本历史响应无效' }); return value.revisions },
  preview(alertTypeId: string, recognitionCategoryId: string, signal?: AbortSignal) { return apiClient.request<{ matched: boolean; matchKey: { alertTypeId: string; recognitionCategoryId: string }; entry: KnowledgeEntry | null }>(base + '/knowledge-entries/match-preview', { method: 'POST', json: { alertTypeId, recognitionCategoryId }, signal }) },
} }
export const alertAdviceApi = {
  ...knowledgeApi('/alert-advice'),
  base(signal?: AbortSignal) { return apiClient.request<ProjectKnowledgeBase>('/alert-advice/base', { signal }) },
  upgrade(version: number, expectedRevision: number) { return apiClient.request<ProjectKnowledgeBase>('/alert-advice/base/upgrade', { method: 'POST', json: { version, expectedRevision } }) },
  override(entry: KnowledgeEntry, payload: KnowledgePayload, status = entry.status) { return apiClient.request<KnowledgeEntry>('/alert-advice/knowledge-overrides', { method: 'POST', json: { ...payload, status, inheritedEntryId: entry.entryId, expectedBaseRevision: entry.baseRevision } }).then(assertEntry) },
}
export const systemKnowledgeApi = {
  ...knowledgeApi('/platform/alert-advice'),
  catalog(signal?: AbortSignal) { return apiClient.request<{ entries: KnowledgeEntry[]; revision: number }>('/platform/alert-advice/knowledge-entries', { signal }) },
  versions(signal?: AbortSignal) { return apiClient.request<{ versions: SystemKnowledgeVersion[] }>('/platform/alert-advice/versions', { signal }) },
  publish(expectedRevision: number, notes: string) { return apiClient.request('/platform/alert-advice/publish', { method: 'POST', json: { expectedRevision, notes } }) },
  release(version: number) { return apiClient.request<{ entries: KnowledgeEntry[] }>('/platform/alert-advice/versions/' + version) },
}

const failures: Record<string, string> = {
  REVISION_CONFLICT: '资料已被其他操作更新。请关闭编辑窗并刷新列表，再基于最新版本修改。',
  ACTIVE_MATCH_KEY_CONFLICT: '当前项目已存在相同告警类型与识别分类的资料。',
  KNOWLEDGE_ENTRY_INVALID: '资料字段不符合约束，请检查步骤、制度原文和适用范围。',
}
export function adviceError(error: unknown) { return error instanceof ApiError && failures[error.code] ? failures[error.code] : error instanceof Error ? error.message : '操作失败，请刷新后重试' }
