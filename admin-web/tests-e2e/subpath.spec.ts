import { expect, test } from '@playwright/test'

test.beforeEach(({}, info) => {
  test.skip(!['subpath-chromium', 'direct-chromium'].includes(info.project.name), 'Requires isolated routing fixture')
})

test('slash redirect stays relative and root admin remains another project', async ({ request }, info) => {
  test.skip(info.project.name !== 'subpath-chromium')
  const response = await request.get('/video/admin?pane=upload', { maxRedirects: 0 })
  expect(response.status()).toBe(307)
  expect(response.headers().location).toBe('admin/?pane=upload')
  expect((await request.get('/admin/')).status()).toBe(401)
  const missing = await request.get('/video/admin/assets/not-found.js')
  expect(missing.status()).toBe(404)
})

for (const mount of ['admin', 'admin-next']) {
  test(`real cookie login, navigation, refresh and logout under ${mount}`, async ({ context, page }, info) => {
    const prefix = info.project.name === 'subpath-chromium' ? '/video' : ''
    // Production currently rewrites only stable asset URLs, not preview assets.
    test.skip(Boolean(prefix) && mount === 'admin-next', 'Preview is not exposed by the supplied production proxy')
    const base = `${prefix}/${mount}`
    const errors: string[] = [], escaped: string[] = [], assets: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', req => {
      const path = new URL(req.url()).pathname
      if (req.isNavigationRequest() && path !== base && !path.startsWith(base + '/')) escaped.push(path)
      if (path.includes('/assets/')) assets.push(path)
    })
    await page.goto(base)
    await expect(page).toHaveURL(new RegExp(`${base}/login`))
    await page.getByLabel('账号', { exact: true }).fill('cutover-admin')
    await page.getByLabel('密码', { exact: true }).fill('cutover-test-password')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.getByRole('button', { name: '进入 验收项目' })).toBeVisible()
    expect(new URL(page.url()).pathname.startsWith(base + '/')).toBe(true)
    const cookie = (await context.cookies()).find(c => c.name === 'aiyolo_session')
    expect(cookie?.httpOnly).toBe(true)
    // Platform account management uses real handlers in the isolated fixture.
    await page.goto(`${base}/platform/accounts`)
    await expect(page.getByRole('heading', { level: 1, name: '平台账号', exact: true })).toBeVisible()
    await page.getByRole('link', { name: '平台项目', exact: true }).click()
    await expect(page).toHaveURL(`${base}/platform/projects`)
    await expect(page.getByRole('heading', { level: 1, name: '平台项目', exact: true })).toBeVisible()
    await page.reload()
    await expect(page).toHaveURL(`${base}/platform/projects`)
    await expect(page.getByRole('heading', { level: 1, name: '平台项目', exact: true })).toBeVisible()
    await page.goBack()
    await expect(page).toHaveURL(`${base}/platform/accounts`)
    await page.goForward()
    await expect(page).toHaveURL(`${base}/platform/projects`)
    await page.goto(`${base}/platform/accounts?tab=active#account-list`)
    await expect(page.getByRole('heading', { level: 1, name: '平台账号', exact: true })).toBeVisible()
    await page.reload()
    await expect(page).toHaveURL(`${base}/platform/accounts?tab=active#account-list`)
    for (const href of await page.locator('a.nav-link').evaluateAll(links => links.map(link => link.getAttribute('href')))) {
      expect(href?.startsWith(base + '/')).toBe(true)
    }
    if (base.endsWith('-next')) {
      await expect(page.getByRole('link', { name: '打开正式后台 ↗' })).toHaveAttribute('href', `${prefix}/admin/`)
    }
    await page.getByRole('button', { name: '退出登录', exact: true }).click()
    await expect(page).toHaveURL(`${base}/login`)
    await page.reload()
    await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
    // An anonymous deep link must survive the login guard and round trip.
    await page.goto(`${base}/platform/accounts?tab=active#account-list`)
    await expect(page).toHaveURL(new RegExp(`${base}/login[?]redirect=`))
    await page.getByLabel('账号', { exact: true }).fill('cutover-admin')
    await page.getByLabel('密码', { exact: true }).fill('cutover-test-password')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page).toHaveURL(`${base}/platform/accounts?tab=active#account-list`)
    await expect(page.getByRole('heading', { level: 1, name: '平台账号', exact: true })).toBeVisible()
    expect(assets.length).toBeGreaterThan(0)
    expect(assets.every(path => path.startsWith(base + '/assets/'))).toBe(true)
    expect(escaped).toEqual([])
    expect(errors).toEqual([])
  })
}
