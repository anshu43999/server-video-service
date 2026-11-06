// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { authApi, type SessionUser } from '../src/api/auth'
import { ApiClient, apiClient } from '../src/api/client'
import { projectScope } from '../src/api/projectScope'
import { type AccessibleProject } from '../src/api/projects'
import { useProjectsStore } from '../src/stores/projects'
import { useSessionStore } from '../src/stores/session'
import { useAlertsStore } from '../src/features/alerts/store'
import { ManagedWebSocket } from '../src/api/realtime'
import { AdminPreview } from '../src/features/streams/preview'
import { installProjectMonitor } from '../src/app/projectMonitor'
import { createAdminRouter, installSessionGuard } from '../src/app/router'
import { SESSION_EVENT_KEY } from '../src/api/sessionEvents'

const identity: SessionUser = { accountId: 'account-a', username: 'user', role: 'operator', platformRole: 'NORMAL_USER', contractVersion: 'm33-v1' }
const project = (id: string, overrides: Partial<AccessibleProject> = {}): AccessibleProject => ({ projectId: id, projectCode: id, displayName: `项目${id}`, lifecycleState: 'ACTIVE', revision: 1, membershipRevision: 1, projectRole: 'PROJECT_OWNER', platformEntry: false, capabilities: ['project.read', 'project.alerts.read', 'project.streams.view'], ...overrides })
const response = (data: unknown) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
const defer = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: state })
}
let pinia: ReturnType<typeof createPinia>
let values: AccessibleProject[]
let me: SessionUser
beforeEach(() => {
  pinia = createPinia(); setActivePinia(pinia); projectScope.enable()
  values = [project('a')]; me = { ...identity }
  const session = useSessionStore(); session.user = { ...identity }; session.phase = 'authenticated'
  vi.spyOn(authApi, 'me').mockImplementation(async () => me)
  vi.stubGlobal('fetch', vi.fn(async () => response({ contractVersion: 'm33-v1', projects: values })))
})
afterEach(() => { projectScope.clear(); projectScope.enabled = false; projectScope.onDenied = undefined; disposePinia(pinia); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

describe('project selection and fail-closed lifecycle', () => {
  it('automatically enters one member project and requires a choice for multiple projects', async () => {
    const store = useProjectsStore(); await store.enter(); expect(store.current?.projectId).toBe('a')
    values.push(project('b')); await store.enter(); expect(store.phase).toBe('choosing'); expect(projectScope.projectId).toBeNull()
    await store.enter('b'); expect(store.current?.projectId).toBe('b')
  })
  it('requires explicit platform entry even for one project', async () => {
    me = { ...identity, platformRole: 'PLATFORM_ADMIN' }; useSessionStore().user = me
    values = [project('a', { platformEntry: true, projectRole: null })]
    const store = useProjectsStore(); await store.enter(); expect(store.phase).toBe('choosing')
    await store.enter('a'); expect(store.current?.platformEntry).toBe(true)
  })
  it('exposes an empty state and does not guess an invalid deep-link project', async () => {
    values = []; const store = useProjectsStore(); await store.enter(); expect(store.phase).toBe('empty')
    values = [project('a')]; await store.enter('unknown'); expect(store.phase).toBe('unavailable'); expect(projectScope.projectId).toBeNull()
  })
  it('rejects an old identity protocol and an incompatible project response', async () => {
    me = { ...identity, contractVersion: undefined }; const store = useProjectsStore(); await store.enter(); expect(store.phase).toBe('error')
    me = identity; vi.stubGlobal('fetch', vi.fn(async () => response({ projects: values })))
    await store.enter(); expect(store.phase).toBe('error'); expect(store.current).toBeNull()
  })
  it.each(['removed', 'suspended', 'role'] as const)('clears current state when permission changes: %s', async kind => {
    const store = useProjectsStore(); await store.enter('a')
    values = kind === 'removed' ? [] : [project('a', kind === 'suspended' ? { lifecycleState: 'SUSPENDED', revision: 2 } : { projectRole: 'PROJECT_USER', membershipRevision: 2 })]
    await store.revalidate(); expect(store.phase).toBe('unavailable'); expect(store.current).toBeNull(); expect(projectScope.projectId).toBeNull()
  })
  it('does not retain data when server validation fails', async () => {
    const store = useProjectsStore(); await store.enter('a')
    vi.mocked(authApi.me).mockRejectedValueOnce(new Error('offline')); await store.revalidate()
    expect(store.phase).toBe('error'); expect(store.current).toBeNull()
  })
  it('rejects stale project lists during rapid switching', async () => {
    const slow = defer<Response>(); vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(slow.promise).mockImplementation(async () => response({ contractVersion: 'm33-v1', projects: [project('a'), project('b')] })))
    const store = useProjectsStore(); const first = store.enter('a'); await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    await store.enter('b'); slow.resolve(response({ contractVersion: 'm33-v1', projects: [project('a')] })); await first
    expect(store.current?.projectId).toBe('b')
  })
  it('keeps project choices out of browser storage', async () => {
    localStorage.clear(); sessionStorage.clear(); await useProjectsStore().enter('a')
    expect(localStorage.length + sessionStorage.length).toBe(0)
  })
})

describe('project resource generation', () => {
  it('routes REST, media and sockets to an explicit project, never another project', () => {
    expect(() => projectScope.path('/aiyoloapi/alerts')).toThrow()
    projectScope.enter('a')
    for (const path of ['alerts', 'streams/x/preview?connection=1', 'alerts/ws', 'rules', 'models']) expect(projectScope.path(`/aiyoloapi/${path}`)).toBe(`/aiyoloapi/projects/a/${path}`)
    expect(() => projectScope.path('/aiyoloapi/projects/b/alerts')).toThrow()
    projectScope.clear(); expect(projectScope.path('/aiyoloapi/models')).toBe('/aiyoloapi/models')
  })
  it('aborts fetch and rejects stale JSON even when a transport ignores cancellation', async () => {
    projectScope.enter('a'); const body = defer<unknown>(); let signal: AbortSignal | undefined
    const client = new ApiClient(async (_url, init) => { signal = init?.signal as AbortSignal; return { ok: true, status: 200, json: () => body.promise } as Response })
    const pending = client.request('/alerts').catch(error => error); await nextTick()
    projectScope.clear(); projectScope.enter('b'); body.resolve({ events: ['secret-a'] })
    expect(signal?.aborted).toBe(true); expect(await pending).toMatchObject({ code: 'project_context_changed' })
  })
  it('clears Pinia alerts and rejects a late list result', async () => {
    projectScope.enter('a'); const slow = defer<Response>(); vi.stubGlobal('fetch', vi.fn(() => slow.promise))
    const store = useAlertsStore(); store.events = [{ eventId: 'secret-a' }]; const pending = store.refresh()
    projectScope.clear(); projectScope.enter('b'); slow.resolve(response({ events: [{ eventId: 'secret-a' }] })); await pending
    expect(store.events).toEqual([]); expect(store.phase).toBe('idle')
  })
  it('closes sockets and suppresses queued messages and reconnect timers', () => {
    vi.useFakeTimers(); projectScope.enter('a')
    const sock = { close: vi.fn(), onopen: null, onmessage: null, onclose: null, onerror: null } as unknown as WebSocket
    const message = vi.fn(), create = vi.fn(() => sock)
    const managed = new ManagedWebSocket({ path: '/aiyoloapi/alerts/ws', location: { host: 'test', protocol: 'https:' }, createSocket: create, onMessage: message })
    managed.start(); const queued = sock.onmessage; projectScope.clear(); queued?.call(sock, { data: '{}' } as MessageEvent); vi.runAllTimers()
    expect(create).toHaveBeenCalledWith('wss://test/aiyoloapi/projects/a/alerts/ws'); expect(sock.close).toHaveBeenCalled(); expect(message).not.toHaveBeenCalled(); expect(create).toHaveBeenCalledOnce()
  })
  it('aborts media, clears frames and revokes object URLs', async () => {
    projectScope.enter('a'); const frame = vi.fn(), revoke = vi.fn()
    const preview = new AdminPreview({ onFrame: frame, revokeObjectURL: revoke, createObjectURL: () => 'blob:secret', fetchImpl: async () => new Response(new Blob(['jpeg']), { headers: { 'Content-Type': 'image/jpeg' } }) })
    preview.start('/aiyoloapi/streams/x/preview?connection=1'); await vi.waitFor(() => expect(frame).toHaveBeenCalledWith('blob:secret'))
    projectScope.clear(); expect(revoke).toHaveBeenCalledWith('blob:secret'); expect(frame).toHaveBeenLastCalledWith('')
  })
  it('aborts XHR uploads on context reset', async () => {
    projectScope.enter('a')
    class Upload { upload = {}; onabort?: () => void; open() {} setRequestHeader() {} send() {} abort() { this.onabort?.() } }
    vi.stubGlobal('XMLHttpRequest', Upload)
    const pending = apiClient.uploadWithProgress('/conversion/uploads', new Blob(['weight'])).catch(e => e)
    projectScope.clear(); expect(await pending).toMatchObject({ kind: 'cancelled' })
  })
})

describe('routes and cross-tab invalidation', () => {
  it('restores explicit deep links and rejects unknown or malformed project queries', async () => {
    values = [project('a'), project('b')]; const router = createAdminRouter(); installSessionGuard(router, useSessionStore())
    await router.push('/alerts?project=b&event=same-id'); expect(useProjectsStore().current?.projectId).toBe('b'); expect(router.currentRoute.value.query.event).toBe('same-id')
    await router.push('/alerts?project=unknown'); expect(router.currentRoute.value.name).toBe('projects'); expect(useProjectsStore().current).toBeNull()
    await router.push('/alerts?project=a&project=b'); expect(router.currentRoute.value.name).toBe('projects')
  })
  it('keeps the active project mounted when revisiting the project picker', async () => {
    const projects = useProjectsStore(); await projects.enter('a')
    const router = createAdminRouter(); installSessionGuard(router, useSessionStore()); const epoch = projects.epoch
    await router.push('/projects')
    expect(projects.phase).toBe('ready')
    expect(projects.current?.projectId).toBe('a')
    expect(projects.epoch).toBe(epoch)
    await router.push('/overview?project=a')
    expect(router.currentRoute.value.name).toBe('overview')
    expect(projects.current?.projectId).toBe('a')
  })
  it('a session-change notification clears data synchronously before validation', async () => {
    const projects = useProjectsStore(); await projects.enter('a'); const session = useSessionStore(), router = createAdminRouter()
    const slow = defer<SessionUser>(); vi.mocked(authApi.me).mockReturnValueOnce(slow.promise)
    const stop = installProjectMonitor(router, session, projects)
    window.dispatchEvent(new StorageEvent('storage', { key: SESSION_EVENT_KEY, newValue: 'changed' }))
    expect(projects.current).toBeNull(); expect(projectScope.projectId).toBeNull()
    slow.resolve(identity); await vi.waitFor(() => expect(projects.phase).toBe('choosing')); stop()
  })

  it('softly revalidates on window focus without remounting the active project', async () => {
    const projects = useProjectsStore(); await projects.enter('a')
    const session = useSessionStore(), router = createAdminRouter(), epoch = projects.epoch
    const stop = installProjectMonitor(router, session, projects)
    window.dispatchEvent(new Event('focus'))
    await vi.waitFor(() => expect(authApi.me).toHaveBeenCalledTimes(2))
    expect(projects.current?.projectId).toBe('a')
    expect(projects.phase).toBe('ready')
    expect(projects.epoch).toBe(epoch)
    expect(projectScope.projectId).toBe('a')
    stop()
  })

  it('does not report a suspended project when the picker has no active project', async () => {
    const projects = useProjectsStore(); await projects.enter(undefined, true)
    const session = useSessionStore(), router = createAdminRouter()
    const stop = installProjectMonitor(router, session, projects)
    setVisibility('hidden'); document.dispatchEvent(new Event('visibilitychange'))
    expect(projects.phase).toBe('choosing')
    expect(projects.message).toBe('')
    setVisibility('visible'); stop()
  })

  it('softly revalidates after a brief visibility loss', async () => {
    const projects = useProjectsStore(); await projects.enter('a')
    const session = useSessionStore(), router = createAdminRouter(), epoch = projects.epoch
    const stop = installProjectMonitor(router, session, projects)
    setVisibility('hidden'); document.dispatchEvent(new Event('visibilitychange'))
    setVisibility('visible'); document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(authApi.me).toHaveBeenCalledTimes(2))
    expect(projects.current?.projectId).toBe('a')
    expect(projects.phase).toBe('ready')
    expect(projects.epoch).toBe(epoch)
    stop()
  })

  it('clears the suspension notice after a successful visibility revalidation', async () => {
    vi.useFakeTimers()
    const projects = useProjectsStore(); await projects.enter('a')
    const session = useSessionStore(), router = createAdminRouter()
    const stop = installProjectMonitor(router, session, projects)
    setVisibility('hidden'); document.dispatchEvent(new Event('visibilitychange'))
    expect(projects.current?.projectId).toBe('a')
    vi.advanceTimersByTime(5 * 60 * 1000)
    expect(projects.current).toBeNull()
    expect(projects.message).toBe('页面离开后已暂停项目数据；返回时重新验证权限')
    setVisibility('visible'); document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(projects.message).toBe(''))
    expect(projects.phase).toBe('choosing')
    stop()
  })
})
