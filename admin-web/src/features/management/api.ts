import { apiClient } from '../../api/client'
import { ApiError } from '../../api/errors'
import type { PlatformRole } from '../../api/auth'
export type { PlatformRole } from '../../api/auth'
export type ProjectRole = 'PROJECT_OWNER' | 'PROJECT_USER'
export interface ProjectRecord { projectId: string; projectCode: string; displayName: string; lifecycleState: 'ACTIVE' | 'SUSPENDED' | 'ARCHIVED'; revision: number }
export interface AccountRecord { accountId: string; username: string; platformRole: PlatformRole; enabled: boolean; revision: number }
export interface MemberRecord { projectId: string; accountId: string; username: string; accountEnabled: boolean; projectRole: ProjectRole; enabled: boolean; revision: number }
export interface AuditRecord { auditId: string; occurredAt: string; requestId: string | null; actorAccountId: string | null; actorServicePrincipalId: string | null; platformRole: string | null; projectId: string | null; projectRole: string | null; action: string; targetType: string; targetId: string | null; previousRevision: number | null; newRevision: number | null; outcome: string; failureCode: string | null }
export interface AuditPage { events: AuditRecord[]; nextCursor: string | null }
const segment = encodeURIComponent
function records<T extends { revision: number }>(items: T[], key: keyof T): T[] {
  if (!Array.isArray(items) || items.some(v => !v || typeof v[key] !== 'string' || !v[key] || !Number.isInteger(v.revision) || v.revision < 1)) throw new ApiError({ kind: 'invalid-response', message: '管理接口响应无效，请刷新核验' })
  return items
}
export const managementApi = {
  async projects(signal?: AbortSignal) { return records((await apiClient.request<{ projects: ProjectRecord[] }>('/platform/projects', { signal })).projects, 'projectId') },
  createProject(value: { projectCode: string; displayName: string; ownerAccountId: string }, signal?: AbortSignal) { return apiClient.request<ProjectRecord>('/platform/projects', { method: 'POST', json: value, signal }) },
  editProject(value: ProjectRecord, signal?: AbortSignal) { return apiClient.request<ProjectRecord>(`/platform/projects/${segment(value.projectId)}`, { method: 'PATCH', json: { expectedRevision: value.revision, displayName: value.displayName, projectCode: value.projectCode }, signal }) },
  lifecycle(value: ProjectRecord, action: 'suspend' | 'archive' | 'restore', signal?: AbortSignal) { return apiClient.request<ProjectRecord>(`/platform/projects/${segment(value.projectId)}/${action}`, { method: 'POST', json: { expectedRevision: value.revision }, signal }) },
  async accounts(signal?: AbortSignal) { return records((await apiClient.request<{ accounts: AccountRecord[] }>('/platform/accounts', { signal })).accounts, 'accountId') },
  createAccount(value: { username: string; password: string; platformRole: PlatformRole }, signal?: AbortSignal) { return apiClient.request<AccountRecord>('/platform/accounts', { method: 'POST', json: value, signal }) },
  editAccount(value: AccountRecord, signal?: AbortSignal) { return apiClient.request<AccountRecord>(`/platform/accounts/${segment(value.accountId)}`, { method: 'PATCH', json: { expectedRevision: value.revision, platformRole: value.platformRole, enabled: value.enabled }, signal }) },
  async members(projectId: string, signal?: AbortSignal) { return records((await apiClient.request<{ members: MemberRecord[] }>(`/projects/${segment(projectId)}/members`, { signal })).members, 'accountId') },
  addMember(projectId: string, value: { accountId: string; projectRole: ProjectRole }, signal?: AbortSignal) { return apiClient.request<MemberRecord>(`/projects/${segment(projectId)}/members`, { method: 'POST', json: value, signal }) },
  editMember(value: MemberRecord, signal?: AbortSignal) { return apiClient.request<MemberRecord>(`/projects/${segment(value.projectId)}/members/${segment(value.accountId)}`, { method: 'PATCH', json: { expectedRevision: value.revision, projectRole: value.projectRole, enabled: value.enabled }, signal }) },
  removeMember(value: MemberRecord, signal?: AbortSignal) { return apiClient.request(`/projects/${segment(value.projectId)}/members/${segment(value.accountId)}`, { method: 'DELETE', query: { expectedRevision: value.revision }, response: 'void', signal }) },
  transfer(projectId: string, from: MemberRecord, to: MemberRecord, signal?: AbortSignal) { return apiClient.request(`/projects/${segment(projectId)}/transfer-owner`, { method: 'POST', json: { fromAccountId: from.accountId, toAccountId: to.accountId, expectedFromRevision: from.revision, expectedToRevision: to.revision }, signal }) },
  async audit(projectId: string | null, cursor?: string, signal?: AbortSignal, filters: Record<string,string> = {}) {
    const value = await apiClient.request<AuditPage>(projectId ? `/projects/${segment(projectId)}/audit` : '/platform/audit', { query: { ...filters, limit: 25, cursor }, signal })
    if (!value || !Array.isArray(value.events) || (value.nextCursor !== null && typeof value.nextCursor !== 'string')) throw new ApiError({ kind: 'invalid-response', message: '审计响应无效' })
    return value
  },
}

const failures: Record<string, string> = {
  scene_input_not_supported: '场景、模型成员或运行方案的输入类型不一致，请核对图片和视频输入配置。',
  revision_conflict: '数据已被其他操作修改。请关闭弹窗并刷新，再基于最新版本重新编辑；不会覆盖他人的更改。',
  last_project_owner: '不能移除或停用最后一位有效负责人。请先完成负责人移交。',
  last_platform_admin: '必须保留至少一位启用的平台超级管理员。',
  project_code_exists: '项目代码已存在，请使用其他代码。', username_exists: '账号名已存在，请刷新确认是否已创建。',
  account_exists: '账号名已存在，请刷新确认是否已创建。', membership_exists: '该账号已有成员关系，请刷新后编辑现有成员。',
  project_role_escalation_forbidden: '项目负责人只能维护普通项目用户，不能直接授予负责人角色。',
  owner_transfer_forbidden: '只能移交自己的负责人身份。', target_not_eligible: '接收人必须是账号和成员关系均启用的现有成员。',
  lifecycle_conflict: '当前项目状态不支持此操作，请刷新状态后重试。',
}
export function managementError(error: unknown) {
  if (error instanceof ApiError && failures[error.code]) return failures[error.code]
  return error instanceof Error ? error.message : '操作失败，请核验服务器状态后重试'
}
