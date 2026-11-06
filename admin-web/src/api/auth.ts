import { apiClient } from './client'

export type UserRole = 'admin' | 'operator'
export type PlatformRole = 'PLATFORM_ADMIN' | 'NORMAL_USER'
export interface SessionUser {
  username: string; role: UserRole
  accountId?: string
  platformRole?: PlatformRole
  contractVersion?: string
}
export function platformRoleLabel(role?: PlatformRole) {
  return role === 'PLATFORM_ADMIN' ? '平台超级管理员（管理全平台）' : '普通平台账号（项目成员/项目负责人使用）'
}
export interface AuthStatus { setupRequired: boolean; authenticated: boolean; user: SessionUser | null }
interface AuthResponse { accessToken: string; tokenType: string; expiresIn: number; user: SessionUser }

const authRequest = { skipSessionCheck: true } as const

export const authApi = {
  status: () => apiClient.request<AuthStatus>('/auth/status', authRequest),
  me: () => apiClient.request<SessionUser>('/auth/me', authRequest),
  login: async (username: string, password: string) => {
    const response = await apiClient.request<AuthResponse>('/auth/login', {
      ...authRequest, method: 'POST', json: { username, password },
    })
    return response.user
  },
  setup: async (username: string, password: string) => {
    const response = await apiClient.request<AuthResponse>('/auth/setup', {
      ...authRequest, method: 'POST', json: { username, password },
    })
    return response.user
  },
  logout: () => apiClient.request<{ ok: boolean }>('/auth/logout', { ...authRequest, method: 'POST' }),
}
