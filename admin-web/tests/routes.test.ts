// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest'
import { consoleRoutes, createAdminRouter, visibleNavigationItems, projectNavigationItems } from '../src/app/router'

const expectedRoutes = [
  ['overview', '总览'],
  ['dashboard', '数据看板'],
  ['streams', '视频流'],
  ['alerts', '告警中心'],
  ['push', '报警推送'],
  ['rules', '规则配置'],
  ['models', '模型资产'],
  ['diagnostics', '系统诊断'],
]

describe('admin route map', () => {
  it('exposes the active menu destinations with complete page metadata', () => {
    expect(consoleRoutes.map((route) => [route.path, route.meta?.title])).toEqual(expectedRoutes)
    for (const route of consoleRoutes) {
      expect(route.name).toBe(route.path)
      expect(route.meta?.eyebrow).toBeTruthy()
      expect(route.meta?.description).toBeTruthy()
      expect(route.meta?.roles).toEqual(['admin'])
      expect(route.meta?.navigation).toBe(true)
    }
    const router = createAdminRouter()
    for (const path of ['/projects', '/scenes', '/project-models', '/project-diagnostics', '/alert-knowledge', '/platform/projects', '/platform/accounts', '/platform/audit', '/members', '/project-audit', '/platform/app-updates']) {
      const route = router.resolve(path)
      expect(route.meta.title, path).toBeTruthy()
      expect(route.meta.description, path).toBeTruthy()
    }
  })

  it('derives permission-aware navigation from the route definitions', () => {
    expect(visibleNavigationItems('admin')).toHaveLength(8)
    expect(visibleNavigationItems('operator')).toHaveLength(0)
    expect(visibleNavigationItems()).toHaveLength(0)
  })

  it('resolves direct and unknown deep links inside the admin shell', () => {
    const router = createAdminRouter()
    expect(router.resolve('/rules').name).toBe('rules')
    expect(router.resolve('/verification').name).toBe('unavailable')
    expect(router.resolve('/missing-page').name).toBe('unavailable')
  })

  it('does not register retired legacy data approval routes', () => {
    const router = createAdminRouter()
    expect(router.resolve('/platform/mobile-legacy-approvals').name).toBe('unavailable')
    expect(router.resolve('/mobile-legacy-approval/requests/example').name).toBe('unavailable')
  })
})
