import { apiClient } from './client'
import { ApiError } from './errors'
import { platformRoleLabel } from './auth'

export interface AccessibleProject {
  projectId: string
  projectCode: string
  displayName: string
  lifecycleState: 'ACTIVE' | 'SUSPENDED' | 'ARCHIVED'
  revision: number
  membershipRevision: number | null
  projectRole: 'PROJECT_OWNER' | 'PROJECT_USER' | null
  platformEntry: boolean
  capabilities: string[]
}

export async function accessibleProjects(signal?: AbortSignal): Promise<AccessibleProject[]> {
  const value = await apiClient.request<{ contractVersion: string; projects: AccessibleProject[] }>('/auth/projects', { signal })
  if (!value || value.contractVersion !== 'm33-v1' || !Array.isArray(value.projects) || value.projects.some(p =>
    !p || typeof p.projectId !== 'string' || !p.projectId || typeof p.displayName !== 'string' ||
    typeof p.projectCode !== 'string' || !['ACTIVE', 'SUSPENDED', 'ARCHIVED'].includes(p.lifecycleState) ||
    !Number.isInteger(p.revision) || p.revision < 1 || typeof p.platformEntry !== 'boolean' ||
    (!p.platformEntry && (p.projectRole === null || !Number.isInteger(p.membershipRevision) || (p.membershipRevision ?? 0) < 1)) ||
    ![null, 'PROJECT_OWNER', 'PROJECT_USER'].includes(p.projectRole) ||
    !Array.isArray(p.capabilities) || p.capabilities.some(c => typeof c !== 'string'))) {
    throw new ApiError({ kind: 'invalid-response', code: 'project_contract_required', message: '项目协议不兼容，请先升级服务器；已停止业务数据请求' })
  }
  if (new Set(value.projects.map(p => p.projectId)).size !== value.projects.length) throw new ApiError({ kind: 'invalid-response', message: '项目列表无效' })
  return value.projects
}

export function projectRoleLabel(project: AccessibleProject) {
  return project.platformEntry ? `${platformRoleLabel('PLATFORM_ADMIN')} · 显式进入` : project.projectRole === 'PROJECT_OWNER' ? '项目负责人' : '项目用户'
}
