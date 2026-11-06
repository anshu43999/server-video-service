import { adminPath } from './helpers/navigation'
import { fixtureUser, fixtureProjects, fixtureProject } from './helpers/project-fixture'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'

async function mockAdminSession(context: BrowserContext) {
  // The shell owns a global alert subscription; keep this fixture fully local.
  await context.routeWebSocket('**/aiyoloapi/projects/*/alerts/ws', () => {})
  await context.route('**/aiyoloapi/**', route => {
    const path = new URL(route.request().url()).pathname
    if(path.endsWith('/auth/projects'))return route.fulfill({json:fixtureProjects()})
    if(path.endsWith('/projects/fixture-project'))return route.fulfill({json:fixtureProject})
    const payload = path.endsWith('/rules/audit') ? { audit: [] }
      : path.endsWith('/rules') ? { rules: [] }
      : path.endsWith('/capabilities/sources') ? { sources: [] }
      : path.endsWith('/verification/config') ? { enabled: false, imageEgressAuthorized: false, dailyLimit: 100, callsToday: 0, modelId: '', providerConfigured: false }
      : path.endsWith('/streams') ? [] : { events: [] }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) })
  })
  await context.route('**/aiyoloapi/auth/status', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ setupRequired: false, authenticated: true, user: { username: 'visual-admin', role: 'admin' } }),
  }))
  await context.route('**/aiyoloapi/auth/me', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify(fixtureUser()),
  }))
}

function collectErrors(page: Page) {
  const errors: string[] = []
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function expectNoHorizontalOverflow(page: Page) {
  const sizes = await page.evaluate(() => ({ viewport: window.innerWidth, content: document.documentElement.scrollWidth, scrollX: window.scrollX }))
  expect(sizes.content).toBeLessThanOrEqual(sizes.viewport)
  expect(sizes.scrollX).toBe(0)
}

test('desktop shell keeps all routes and survives a deep-link refresh', async ({ context, page }) => {
  await mockAdminSession(context)
  const errors = collectErrors(page)
  await page.goto(adminPath('/rules'))

  await expect(page.getByRole('heading', { level: 1, name: '规则配置' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '管理后台主导航' }).getByRole('link')).toHaveCount(16)
  await expect(page.getByRole('link', { name: '平台项目', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '平台账号', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '平台审计', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '新增规则' })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: '../evidence/M32/M32-T04-desktop-shell.png', fullPage: true })

  await page.reload()
  await expect(page).toHaveURL(/\/admin(?:-next)?\/rules\?project=fixture-project$/)
  await expect(page.getByRole('heading', { level: 1, name: '规则配置' })).toBeVisible()
  expect(errors).toEqual([])
})

test('narrow shell exposes keyboard-operable navigation without overflow', async ({ context, page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockAdminSession(context)
  const errors = collectErrors(page)
  await page.goto(adminPath('/verification'))

  const menu = page.getByRole('button', { name: '打开导航' })
  await menu.click()
  await expect(page.locator('#primary-navigation')).toHaveClass(/is-open/)
  await expect.poll(async () => (await page.locator('#primary-navigation').boundingBox())?.x).toBe(0)
  await expect(page.getByRole('navigation', { name: '管理后台主导航' }).getByRole('link')).toHaveCount(16)
  await expect(page.getByRole('link', { name: '项目空间' })).toBeFocused()
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: '../evidence/M32/M32-T04-mobile-navigation.png', fullPage: true })

  await page.keyboard.press('Escape')
  await expect(page.locator('#primary-navigation')).not.toHaveClass(/is-open/)
  await expect(menu).toBeFocused()
  await menu.click()
  await page.getByRole('link', { name: '规则配置' }).click()
  await expect(page).toHaveURL(/\/admin(?:-next)?\/rules\?project=fixture-project$/)
  await expect(page.getByRole('heading', { level: 1, name: '规则配置' })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  expect(errors).toEqual([])
})
