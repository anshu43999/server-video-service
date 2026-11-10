import type { Router } from 'vue-router'
import { watch } from 'vue'
import { useProjectsStore } from '../stores/projects'
import { useSessionStore } from '../stores/session'
import { projectScope } from '../api/projectScope'
import { SESSION_EVENT_KEY } from '../api/sessionEvents'

export function installProjectMonitor(router: Router, session: ReturnType<typeof useSessionStore>, projects: ReturnType<typeof useProjectsStore>) {
  let hiddenAt: number | undefined
  let hiddenTimer: number | undefined
  const hiddenGraceMs = 5 * 60 * 1000
  const verify = async (hard = false, background = true) => {
    if (!session.user || (background && document.visibilityState === 'hidden')) return
    await projects.revalidate(hard, background)
  }
  const denied = () => {
    // A missing evidence file is not a revoked membership. Recheck authoritative
    // identity/project revisions; only invalidate when access actually changed.
    void verify(false, false)
  }
  projectScope.onDenied = denied
  // Regain focus frequently happens when users switch applications. A soft
  // revalidation keeps the current page mounted while still detecting revoked
  // access or changed project revisions.
  const focus = () => { void verify() }
  // bfcache can miss session events/timers: discard that context, not just mask it.
  const pageshow = (event: PageTransitionEvent) => { void verify(event.persisted, !event.persisted) }
  const visibility = () => {
    if (document.visibilityState === 'hidden') {
      hiddenAt = Date.now()
      if (hiddenTimer !== undefined) window.clearTimeout(hiddenTimer)
      hiddenTimer = window.setTimeout(() => {
        hiddenTimer = undefined
        if (document.visibilityState === 'hidden' && (projects.current || projectScope.projectId || projects.platformReady)) {
          projects.invalidate('页面离开后已暂停项目数据；返回时重新验证权限')
        }
      }, hiddenGraceMs)
      return
    }
    if (hiddenTimer !== undefined) window.clearTimeout(hiddenTimer)
    hiddenTimer = undefined
    const hiddenDuration = hiddenAt === undefined ? 0 : Date.now() - hiddenAt
    hiddenAt = undefined
    void verify(hiddenDuration >= hiddenGraceMs)
  }
  const storage = (event: StorageEvent) => {
    if (event.key !== SESSION_EVENT_KEY) return
    projects.invalidate('其他标签页的账号会话已变化，请重新验证并选择项目')
    void verify()
  }
  const offline = () => projects.invalidate('网络已断开，项目数据已清空；恢复连接后请重新验证')
  const stop = watch(() => session.phase, phase => {
    if (phase === 'anonymous') void router.replace({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
  }, { flush: 'sync' })
  const timer = window.setInterval(() => { void verify() }, 15_000)
  window.addEventListener('focus', focus)
  window.addEventListener('pageshow', pageshow)
  window.addEventListener('storage', storage)
  window.addEventListener('offline', offline)
  window.addEventListener('online', focus)
  document.addEventListener('visibilitychange', visibility)
  return () => {
    clearInterval(timer); if (hiddenTimer !== undefined) window.clearTimeout(hiddenTimer); stop(); projectScope.onDenied = undefined
    window.removeEventListener('focus', focus); window.removeEventListener('pageshow', pageshow)
    window.removeEventListener('storage', storage); window.removeEventListener('offline', offline)
    window.removeEventListener('online', focus)
    document.removeEventListener('visibilitychange', visibility)
  }
}
