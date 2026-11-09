import { describe, expect, it } from 'vitest'
import { adminHistoryBase, stableAdminHref } from '../src/app/deploymentPaths'

describe('browser-visible admin base', () => {
  it.each([
    ['/admin', '/admin/'], ['/admin/login', '/admin/'],
    ['/admin-next/overview', '/admin-next/'],
    ['/video/admin', '/video/admin/'], ['/video/admin/', '/video/admin/'],
    ['/video/admin/login', '/video/admin/'],
    ['/video/admin/platform/app-updates', '/video/admin/'],
    ['/video/admin-next/models', '/video/admin-next/'],
  ])('keeps the public prefix of %s', (path, base) => {
    expect(adminHistoryBase(path, '/admin/')).toBe(base)
  })
  it.each(['/video/administrator', '/videos/admin/', '//evil/admin/', '/other/admin/', '/'])('does not infer a mount from %s', path => {
    expect(adminHistoryBase(path, '/admin-next/')).toBe('/admin-next/')
  })
  it('keeps preview-to-stable navigation inside the deployment', () => {
    expect(stableAdminHref('/video/admin-next/models')).toBe('/video/admin/')
    expect(stableAdminHref('/admin-next/models')).toBe('/admin/')
  })
})
