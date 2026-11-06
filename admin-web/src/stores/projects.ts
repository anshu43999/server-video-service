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
  let sequence = 0, controller: AbortController | undefined
  const busy = computed(() => phase.value === 'loading')
  const reset = projectScope.onClear(() => {
    sequence++; controller?.abort(); controller = undefined
    subscriptionRegistry.closeAll()
    current.value = null; projects.value = []; platformReady.value = false; phase.value = 'idle'; epoch.value++
  })
  onScopeDispose(reset)

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
    controller = new AbortController()
    const signal = controller.signal
    phase.value = 'loading'; message.value = ''
    // Flush unmount hooks (pollers, dialogs, evidence URLs) before any new project data loads.
    await nextTick()
    if (run !== sequence) return
    try {
      const identity = session.user?.accountId
      const user = await authApi.me()
      if (run !== sequence) return
      if (user.accountId !== identity || user.platformRole !== session.user?.platformRole) {
        invalidate('账号会话已变化，请重新验证并选择项目')
        await session.restore()
        return
      }
      session.user = user
      if (!contractReady()) throw new ApiError({ code: 'project_contract_required', message: '项目协议不兼容，请升级服务器后重试' })
      const values = await accessibleProjects(signal)
      if (run !== sequence) return
      projects.value = values
      const id = requested ?? (!choose && !session.isAdmin && values.length === 1 && !values[0].platformEntry ? values[0].projectId : undefined)
      if (!id) { phase.value = values.length ? 'choosing' : 'empty'; return }
      const project = values.find(p => p.projectId === id)
      if (!project) { phase.value = 'unavailable'; message.value = '项目不存在或当前账号已无访问权限。未加载任何项目数据。'; return }
      projectScope.enter(project.projectId)
      await apiClient.request(`/projects/${encodeURIComponent(project.projectId)}`, { signal })
      if (run !== sequence) return
      current.value = project
      phase.value = 'ready'
    } catch (error) { if (run === sequence) { projectScope.clear(); fail(error) } }
  }
  async function ensure(requested?: string) {
    if (current.value && phase.value === 'ready' && (!requested || current.value.projectId === requested)) return
    await enter(requested)
  }
  function invalidate(reason: string) { projectScope.clear(); phase.value = 'unavailable'; message.value = reason }

  // Compare identity and permission revisions against the server, never against cached claims.
  async function revalidate(hard = false) {
    const previous = current.value
    const identity = session.user?.accountId
    if (!identity) return
    const wasPlatformReady = platformReady.value
    if (hard) { projectScope.clear(); phase.value = 'loading' }
    const run = sequence
    try {
      const user = await authApi.me()
      if (run !== sequence) return
      if (user.accountId !== identity || user.platformRole !== session.user?.platformRole) {
        invalidate('账号会话已变化，请重新验证并选择项目')
        await session.restore()
        return
      }
      session.user = user
      if (!contractReady()) { invalidate('项目协议不兼容，请升级服务器后重试'); return }
      const values = await accessibleProjects()
      if (run !== sequence) return
      message.value = ''
      if (previous) {
        const updated = values.find(p => p.projectId === previous.projectId)
        if (!updated || JSON.stringify(updated) !== JSON.stringify(previous)) {
          invalidate('项目状态或成员权限已变化，请重新选择项目')
          return
        }
        if (hard) await enter(previous.projectId)
      } else if (hard && wasPlatformReady && session.isAdmin) { platformReady.value = true; phase.value = 'idle' }
      else if (hard) { projects.value = values; phase.value = values.length ? 'choosing' : 'empty' }
      else projects.value = values
    } catch (error) {
      if (run !== sequence) return
      projectScope.clear(); fail(error)
    }
  }
  return { phase, projects, current, message, epoch, platformReady, busy, contractReady, ensure, enter, invalidate, revalidate }
})
