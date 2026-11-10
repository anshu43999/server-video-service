import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { apiClient, type SessionCheck } from '../api/client'
import { authApi, type SessionUser } from '../api/auth'
import { ApiError, isApiError } from '../api/errors'
import { subscriptionRegistry } from '../api/realtime'
import { projectScope } from '../api/projectScope'
import { notifySessionChange } from '../api/sessionEvents'

export type SessionPhase = 'idle' | 'restoring' | 'anonymous' | 'authenticated' | 'restricted' | 'error'

export const useSessionStore = defineStore('session', () => {
  const phase = ref<SessionPhase>('idle')
  const setupRequired = ref(false)
  const user = ref<SessionUser | null>(null)
  const message = ref('')
  const logoutUnconfirmed = ref(false)
  let restoring: Promise<void> | undefined
  let verifying: Promise<SessionCheck> | undefined
  let identityGeneration = 0
  let permissionVerifier: (() => Promise<SessionCheck>) | undefined
  function setPermissionVerifier(verifier: () => Promise<SessionCheck>) {
    permissionVerifier = verifier
    return () => { if (permissionVerifier === verifier) permissionVerifier = undefined }
  }

  const isAdmin = computed(() => user.value?.platformRole === 'PLATFORM_ADMIN')

  function applyUser(value: SessionUser) {
    if (user.value && (user.value.accountId !== value.accountId || user.value.platformRole !== value.platformRole)) projectScope.clear()
    user.value = value
    phase.value = 'authenticated'
    message.value = ''
    logoutUnconfirmed.value = false
  }

  function expire(reason = '') {
    identityGeneration++
    projectScope.clear()
    subscriptionRegistry.closeAll()
    user.value = null
    phase.value = 'anonymous'
    message.value = reason
  }

  async function restore() {
    if (restoring) return restoring
    const generation = ++identityGeneration
    restoring = (async () => {
      phase.value = 'restoring'
      message.value = ''
      try {
        const status = await authApi.status()
        if (generation !== identityGeneration) return
        setupRequired.value = status.setupRequired
        if (!status.authenticated) { expire(); return }
        const account = await authApi.me()
        if (generation === identityGeneration) applyUser(account)
      } catch (error) {
        if (generation !== identityGeneration) return
        projectScope.clear()
        user.value = null
        phase.value = isApiError(error) && error.status === 401 ? 'anonymous' : 'error'
        message.value = error instanceof Error ? error.message : '无法读取登录状态'
      }
    })().finally(() => { restoring = undefined })
    return restoring
  }

  async function submit(username: string, password: string) {
    const generation = ++identityGeneration
    projectScope.clear()
    phase.value = 'restoring'
    try {
      setupRequired.value
        ? await authApi.setup(username, password)
        : await authApi.login(username, password)
      if (generation !== identityGeneration) return
      setupRequired.value = false
      notifySessionChange()
      const account = await authApi.me()
      if (generation === identityGeneration) applyUser(account)
    } catch (error) {
      if (generation === identityGeneration) { user.value = null; phase.value = 'anonymous' }
      throw error
    }
  }

  async function logout() {
    identityGeneration++
    projectScope.clear()
    phase.value = 'restoring'
    subscriptionRegistry.closeAll()
    logoutUnconfirmed.value = false
    try {
      await authApi.logout()
      notifySessionChange()
      expire()
    } catch (error) {
      logoutUnconfirmed.value = true
      phase.value = 'authenticated'
      message.value = '退出未确认，实时连接已停止'
      throw error
    }
  }

  async function verifyAfterUnauthorized(): Promise<SessionCheck> {
    if (permissionVerifier && user.value?.accountId) return permissionVerifier()
    if (verifying) return verifying
    const generation = identityGeneration
    verifying = (async () => {
      try {
        const account = await authApi.me()
        if (generation !== identityGeneration) return 'unknown' as const
        applyUser(account)
        return 'active' as const
      } catch (error) {
        if (generation !== identityGeneration) return 'unknown' as const
        if (error instanceof ApiError && error.status === 401) {
          expire('登录状态已失效，请重新登录')
          return 'expired' as const
        }
        projectScope.clear()
        message.value = '暂时无法确认登录状态'
        return 'unknown' as const
      }
    })().finally(() => { verifying = undefined })
    return verifying
  }

  return { phase, setupRequired, user, message, logoutUnconfirmed, isAdmin, restore, submit, logout, expire, verifyAfterUnauthorized, setPermissionVerifier }
})

export function connectSessionToApi(store: ReturnType<typeof useSessionStore>) {
  apiClient.setUnauthorizedHandler(() => store.verifyAfterUnauthorized())
}
