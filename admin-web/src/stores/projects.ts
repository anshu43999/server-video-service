import { computed, nextTick, onScopeDispose, ref } from 'vue'
import { defineStore } from 'pinia'
import { accessibleProjects, type AccessibleProject } from '../api/projects'
import { authApi } from '../api/auth'
import { ApiError } from '../api/errors'
import { apiClient } from '../api/client'
import { projectScope } from '../api/projectScope'
import { subscriptionRegistry } from '../api/realtime'
import { useSessionStore } from './session'

export type ProjectPhase = 'idle' | 'loading' | 'choosing' | 'empty' | 'ready' | 'unavailable' | 'error'
export const useProjectsStore = defineStore('projects', () => {
  const session = useSessionStore()
  const phase = ref<ProjectPhase>('idle')
  const projects = ref<AccessibleProject[]>([])
  const current = ref<AccessibleProject | null>(null)
  const message = ref('')
  const epoch = ref(0)
  const platformReady = ref(false)
  const verifying = ref(false)
  // Visual trust is separate from the write barrier. Routine checks alone may
  // keep an already verified context visible; writes still fail while verifying.
  const permissionBlocking = ref(false)
  let sequence = 0, controller: AbortController | undefined
  let verification: Promise<boolean> | undefined
  let platformEntry: Promise<boolean> | undefined
  let verifiedAt: number | undefined
  const busy = computed(() => phase.value === 'loading' || verifying.value)
  const reset = projectScope.onClear(() => {
    sequence++; controller?.abort(); controller = undefined
    verification = undefined; platformEntry = undefined; verifying.value = false; permissionBlocking.value = false; verifiedAt = undefined
    subscriptionRegistry.closeAll()
    current.value = null; projects.value = []; platformReady.value = false; phase.value = 'idle'; epoch.value++
  })
  const disconnect = session.setPermissionVerifier(async () => {
    const valid = await revalidate()
    return valid ? 'active' : session.phase === 'anonymous' ? 'expired' : 'unknown'
  })
  onScopeDispose(() => { reset(); disconnect(); controller?.abort() })

  function contractReady() {
    return session.user?.contractVersion === 'm33-v1' && Boolean(session.user.accountId) &&
      ['PLATFORM_ADMIN', 'NORMAL_USER'].includes(session.user.platformRole ?? '')
  }
  function fail(error: unknown) {
    if (error instanceof ApiError && error.status === 401) session.expire('登录状态已失效，请重新登录')
    phase.value = 'error'
    message.value = error instanceof Error ? error.message : '项目权限暂时无法验证，请重试'
  }
  async function enter(requested?: string, choose = false) {
    projectScope.clear()
    const run = ++sequence
    phase.value = 'loading'; message.value = ''
    // Flush unmount hooks (pollers, dialogs, evidence URLs) before any new project data loads.
    await nextTick()
    if (run !== sequence) return
    try {
      if (!await revalidate() || run !== sequence) return
      const values = projects.value
      const id = requested ?? (!choose && !session.isAdmin && values.length === 1 && !values[0].platformEntry ? values[0].projectId : undefined)
      if (!id) { phase.value = values.length ? 'choosing' : 'empty'; return }
      const project = values.find(p => p.projectId === id)
      if (!project) { phase.value = 'unavailable'; message.value = '项目不存在或当前账号已无访问权限。未加载任何项目数据。'; return }
      projectScope.enter(project.projectId)
      await apiClient.request(`/projects/${encodeURIComponent(project.projectId)}`, { signal: controller?.signal })
      if (run !== sequence) return
      current.value = project
      phase.value = 'ready'
    } catch (error) { if (run === sequence) { projectScope.clear(); fail(error) } }
  }
  async function ensure(requested?: string) {
    if (current.value && phase.value === 'ready' && (!requested || current.value.projectId === requested)) {
      if (verification) await verification
      return
    }
    await enter(requested)
  }
  function invalidate(reason: string) { projectScope.clear(); phase.value = 'unavailable'; message.value = reason }

  // One authoritative me/projects pair per context, not a business-data cache.
  // Unchanged verification preserves mounted pages; invalidation still aborts
  // every old request and prevents late responses from restoring old access.
  function revalidate(hard = false, background = false): Promise<boolean> {
    if (hard) projectScope.clear()
    const trusted = verifiedAt !== undefined && (platformReady.value || (phase.value === 'ready' && current.value !== null))
    // Upgrade before coalescing; a later routine event cannot undo a denial.
    if (verification) {
      if (!background || !trusted) permissionBlocking.value = true
      return verification
    }
    if (!session.user?.accountId || session.phase !== 'authenticated' || session.logoutUnconfirmed) {
      if (phase.value === 'loading') {
        phase.value = 'error'
        message.value = session.message || '登录状态尚未确认，请重新登录后重试'
      }
      return Promise.resolve(false)
    }
    const run = sequence, identity = { ...session.user }, previous = current.value
    controller = new AbortController()
    const signal = controller.signal
    verifying.value = true
    permissionBlocking.value = !background || !trusted
    projectScope.verifying = true
    const pending = (async () => {
      try {
        const user = await authApi.me(signal)
        if (run !== sequence || signal.aborted) return false
        if (user.accountId !== identity.accountId || user.platformRole !== identity.platformRole || user.role !== identity.role) {
          invalidate('账号会话已变化，请重新验证并选择项目')
          session.user = user
          return false
        }
        session.user = user
        if (!contractReady()) throw new ApiError({ code: 'project_contract_required', message: '项目协议不兼容，请升级服务器后重试' })
        const values = await accessibleProjects(signal)
        if (run !== sequence || signal.aborted) return false
        if (previous) {
          const updated = values.find(p => p.projectId === previous.projectId)
          if (!updated || JSON.stringify(updated) !== JSON.stringify(previous)) {
            invalidate('项目状态或成员权限已变化，请重新选择项目')
            return false
          }
        }
        projects.value = values; message.value = ''; verifiedAt = Date.now()
        if (!previous && !platformReady.value && phase.value !== 'loading') phase.value = values.length ? 'choosing' : 'empty'
        return true
      } catch (error) {
        if (run === sequence) { projectScope.clear(); fail(error) }
        return false
      }
    })().finally(() => {
      if (verification === pending) { verification = undefined; verifying.value = false; permissionBlocking.value = false; projectScope.verifying = false }
    })
    verification = pending
    return pending
  }
  function leaveForPlatform(): Promise<boolean> {
    if (platformEntry) return platformEntry
    if (platformReady.value) {
      if (verification) return verification
      // Same deadline as the unchanged 15-second monitor. Focus/denied always
      // verify against the server; only navigation within this context reuses it.
      if (verifiedAt !== undefined && Date.now() - verifiedAt < 15_000) return Promise.resolve(true)
      return revalidate(false, true)
    }
    projectScope.clear()
    const run = sequence
    phase.value = 'loading'
    const pending = (async () => {
      await nextTick()
      if (run !== sequence || !await revalidate() || run !== sequence || !session.isAdmin) return false
      platformReady.value = true; phase.value = 'idle'
      return true
    })().finally(() => { if (platformEntry === pending) platformEntry = undefined })
    platformEntry = pending
    return pending
  }
  return { phase, projects, current, message, epoch, platformReady, verifying, permissionBlocking, busy, contractReady, ensure, enter, invalidate, revalidate, leaveForPlatform }
})
