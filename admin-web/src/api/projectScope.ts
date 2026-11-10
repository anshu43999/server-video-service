import { ApiError } from './errors'

/** One scope per tab. Never persist credentials, business data or a shared project selection. */
class ProjectScope {
  enabled = false
  projectId: string | null = null
  generation = 0
  verifying = false
  private resources = new Set<() => void>()
  private listeners = new Set<() => void>()
  onDenied?: () => void

  enable() { this.enabled = true; this.clear() }
  clear() {
    this.verifying = false
    this.projectId = null
    this.generation++
    const resources = [...this.resources]
    this.resources.clear()
    for (const release of resources) { try { release() } catch { /* Continue releasing other resources. */ } }
    for (const reset of this.listeners) { try { reset() } catch { /* Other caches must still clear. */ } }
  }
  enter(projectId: string) { this.projectId = projectId }
  register(release: () => void) { this.resources.add(release); return () => this.resources.delete(release) }
  onClear(reset: () => void) { this.listeners.add(reset); return () => this.listeners.delete(reset) }
  assertCurrent(generation: number) {
    if (this.enabled && generation !== this.generation) throw this.cancelled()
  }
  cancelled() { return new ApiError({ kind: 'cancelled', code: 'project_context_changed', message: '项目上下文已变化，旧请求已取消' }) }
  assertWritable() {
    if (this.enabled && this.verifying) throw new ApiError({ code: 'permission_verification_pending', message: '正在复核权限，请验证完成后再操作' })
  }
  path(path: string) {
    if (!this.enabled) return path
    const explicit = new RegExp('^/aiyoloapi/projects/([^/?]+)(?:/|$)').exec(path)
    if (explicit) {
      if (!this.projectId || decodeURIComponent(explicit[1]) !== this.projectId) throw this.cancelled()
      return path
    }
    if (this.projectId && (path === '/aiyoloapi/models' || path.startsWith('/aiyoloapi/models/'))) {
      return path.replace('/aiyoloapi/', `/aiyoloapi/projects/${encodeURIComponent(this.projectId)}/`)
    }
    if (new RegExp('^/aiyoloapi/(?:streams|alerts|alert-advice|rules|verification|dashboard|delivery|model-assignments|scenes|capabilities/sources)(?:[/?]|$)').test(path)) {
      if (!this.projectId) throw new ApiError({ status: 400, code: 'project_context_required', message: '请先选择并验证项目' })
      return path.replace('/aiyoloapi/', `/aiyoloapi/projects/${encodeURIComponent(this.projectId)}/`)
    }
    return path
  }
}

export const projectScope = new ProjectScope()
