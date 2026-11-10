// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { ApiError } from '../src/api/errors'
import { projectScope } from '../src/api/projectScope'
import { managementApi } from '../src/features/management/api'
import { useManagement } from '../src/features/management/useManagement'
import { platformNavigationItems, projectNavigationItems } from '../src/app/router'
import { platformRoleLabel } from '../src/api/auth'
const defer = <T>() => { let resolve!: (value: T) => void; return { promise: new Promise<T>(r => { resolve = r }), resolve: (v: T) => resolve(v) } }
afterEach(() => { projectScope.clear(); projectScope.enabled = false; vi.restoreAllMocks(); vi.unstubAllGlobals() })
function setup(load: (signal: AbortSignal) => Promise<string[]>) {
  let store!: ReturnType<typeof useManagement<string[]>>
  const wrapper = mount(defineComponent({ setup() { store = useManagement<string[]>([], load); return () => h('div') } }))
  return { store, wrapper }
}
describe('management mutation recovery and scope', () => {
  it('keeps default write reloads but permits explicit status-only actions', async () => {
    const load = vi.fn().mockResolvedValue(['latest']), { store, wrapper } = setup(load)
    const action = vi.fn().mockResolvedValue({}), success = vi.fn()
    await store.run(action, success, false)
    expect(action).toHaveBeenCalledOnce(); expect(success).toHaveBeenCalledOnce(); expect(load).not.toHaveBeenCalled()
    await store.run(action, success)
    expect(load).toHaveBeenCalledOnce(); expect(store.data.value).toEqual(['latest'])
    wrapper.unmount()
  })
  it('explains scene input mismatches in Chinese while preserving conflict refresh protection',async()=>{
    const {store,wrapper}=setup(vi.fn().mockResolvedValue([]))
    const action=vi.fn().mockRejectedValue(new ApiError({status:409,code:'scene_input_not_supported',message:'member input is outside the scene input declaration'}))
    await store.run(action,vi.fn())
    expect(store.mutationError.value).toContain('场景、模型成员或运行方案的输入类型不一致')
    expect(store.mutationError.value).toContain('不会自动重试');expect(store.needsReload.value).toBe(true)
    await store.run(action,vi.fn());expect(action).toHaveBeenCalledOnce();wrapper.unmount()
  })
  it('uses explicit platform role labels that explain the project role boundary', () => {
    expect(platformRoleLabel('NORMAL_USER')).toBe('普通平台账号（项目成员/项目负责人使用）')
    expect(platformRoleLabel('PLATFORM_ADMIN')).toBe('平台超级管理员（管理全平台）')
  })

  it('requires a successful authoritative refresh before retrying conflicting writes', async () => {
    const load = vi.fn().mockResolvedValue(['latest']), { store, wrapper } = setup(load)
    const action = vi.fn().mockRejectedValue(new ApiError({ status: 409, code: 'revision_conflict' })), success = vi.fn()
    await store.run(action, success); expect(store.needsReload.value).toBe(true); expect(success).not.toHaveBeenCalled()
    store.resetMutation(); await store.run(action, success); expect(action).toHaveBeenCalledOnce()
    load.mockRejectedValueOnce(new Error('offline')); await store.refresh(); expect(store.needsReload.value).toBe(true)
    await store.refresh(); expect(store.needsReload.value).toBe(false)
    action.mockResolvedValueOnce({}); await store.run(action, success); expect(success).toHaveBeenCalledOnce(); wrapper.unmount()
  })
  it('does not announce success or load old data after context changes during a write', async () => {
    projectScope.enable(); const gate = defer<void>(), load = vi.fn().mockResolvedValue(['old'])
    const { store, wrapper } = setup(load), success = vi.fn()
    const pending = store.run(() => gate.promise, success); projectScope.clear(); gate.resolve(); await pending
    expect(success).not.toHaveBeenCalled(); expect(load).not.toHaveBeenCalled(); expect(store.notice.value).toBe(''); wrapper.unmount()
  })
  it('aborts on unmount and drops late list results', async () => {
    const gate = defer<string[]>(); let signal!: AbortSignal
    const { store, wrapper } = setup(s => { signal = s; return gate.promise })
    const pending = store.refresh(); wrapper.unmount(); expect(signal.aborted).toBe(true); gate.resolve(['private']); await pending
    expect(store.data.value).toEqual([])
  })
  it('sends revisions and keeps platform lifecycle separate from project membership paths', async () => {
    projectScope.enable()
    const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response('{"members":[]}', { headers: { 'Content-Type': 'application/json' } })); vi.stubGlobal('fetch', fetcher)
    await managementApi.lifecycle({ projectId: 'a', projectCode: 'aaa', displayName: 'A', revision: 7, lifecycleState: 'ACTIVE' }, 'suspend')
    expect(fetcher.mock.calls[0]?.[0]).toBe('/aiyoloapi/platform/projects/a/suspend')
    expect(JSON.parse((fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)).toEqual({ expectedRevision: 7 })
    await expect(managementApi.members('a')).rejects.toMatchObject({ code: 'project_context_changed' })
    projectScope.enter('a'); await managementApi.members('a'); expect(fetcher).toHaveBeenCalledTimes(2)
  })
  it('exposes platform controls only to admins and project controls only by capability', () => {
    const names = (capabilities: string[], admin = false) => projectNavigationItems(capabilities, admin).map(r => r.name)
    expect(names(['project.read'])).not.toContain('members'); expect(names(['project.members.manage'])).toContain('members')
    expect(names(['project.audit.read'])).toContain('project-audit'); expect(names([])).not.toContain('accounts')
    expect(names([], true)).not.toContain('accounts')
    expect(names(['project.read'], true)).toContain('overview')
    expect(names(['project.read'], true)).not.toContain('accounts')
    expect(platformNavigationItems(false).map(r => r.name)).not.toContain('accounts')
    expect(platformNavigationItems(true).map(r => r.name)).toContain('accounts')
  })
})
