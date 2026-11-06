import { expect, test } from '@playwright/test'

test.beforeEach(({}, info) => test.skip(info.project.name !== 'production-chromium', 'Requires real isolated ASGI routes'))

for (const width of [1440, 390]) {
  test(`independent alerts, offline catchup and replay dedupe at ${width}px`, async ({ context, page }) => {
    test.setTimeout(60_000)
    const errors: string[] = []
    const videoRequests: string[] = []
    await page.addInitScript(() => {
      const NativeWebSocket = window.WebSocket
      const sockets: WebSocket[] = []
      Object.assign(window, { alertTestSockets: sockets })
      window.WebSocket = class extends NativeWebSocket {
        constructor(url: string | URL, protocols?: string | string[]) {
          super(url, protocols); sockets.push(this)
        }
      }
    })
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', request => { if (/\/streams\/.*\/(preview|playback|mjpeg|detections)/.test(request.url())) videoRequests.push(request.url()) })
    const login = await context.request.post('/aiyoloapi/auth/login', { data: { username: 'cutover-admin', password: 'cutover-test-password' } })
    expect(login.ok()).toBe(true)
    const identity = await (await context.request.get('/aiyoloapi/auth/me')).json()
    const created = await context.request.post('/aiyoloapi/projects', { data: {
      projectCode: `alert-closure-${width}`, displayName: `告警闭环 ${width}`, ownerAccountId: identity.accountId,
    } })
    expect(created.ok()).toBe(true)
    const projectId = (await created.json()).projectId
    await page.setViewportSize({ width, height: 960 })
    await page.goto(`/admin/alerts?project=${projectId}`)
    await expect(page.getByText('当前没有告警事件')).toBeVisible()
    await expect(page.locator('.realtime-state')).toHaveText('实时同步')
    const endpoint = `/__test__/projects/${projectId}/confirmed-alert`
    expect((await context.request.post(`${endpoint}/first`)).ok()).toBe(true)
    await expect(page.locator('.notice-item')).toHaveCount(1)
    await expect(page.locator('.alert-event-row')).toHaveCount(1)
    await expect(page.locator('.notice-item')).toContainText('test-camera')
    expect((await context.request.post(`${endpoint}/first`)).ok()).toBe(true)
    await expect(page.locator('.notice-item')).toHaveCount(1)
    await expect(page.locator('.alert-event-row')).toHaveCount(1)

    // A notification socket reconnect keeps the validated project and dedupe set.
    await page.evaluate(() => {
      const sockets = (window as unknown as { alertTestSockets: WebSocket[] }).alertTestSockets
      sockets.at(-1)!.close(4000, 'test notification reconnect')
    })
    expect((await context.request.post(`${endpoint}/socket-gap`)).ok()).toBe(true)
    await expect(page.locator('.alert-event-row')).toHaveCount(2)
    await expect(page.locator('.notice-item')).toHaveCount(2)
    expect((await context.request.post(`${endpoint}/socket-gap`)).ok()).toBe(true)
    await expect(page.locator('.notice-item')).toHaveCount(2)
    const notices = await page.locator('.project-alert-notices').boundingBox()
    const main = await page.locator('#main-content').boundingBox()
    expect(notices).not.toBeNull()
    expect(main).not.toBeNull()
    expect(notices!.y + notices!.height).toBeLessThanOrEqual(main!.y)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `../evidence/M34/M34-T05-notices-${width}.png`, fullPage: true, animations: 'disabled' })

    // Keep the browser offline while the isolated server records a new event.
    await context.setOffline(true)
    await page.evaluate(() => window.dispatchEvent(new Event('offline')))
    expect((await context.request.post(`${endpoint}/missed`)).ok()).toBe(true)
    await context.setOffline(false)
    await page.evaluate(() => window.dispatchEvent(new Event('online')))
    // Whole-browser offline is fail-closed: explicitly revalidate before loading.
    await expect(page.locator('.notice-item')).toHaveCount(0)
    await page.getByRole('button', { name: '重新验证项目', exact: true }).click()
    await page.getByRole('button', { name: `进入 告警闭环 ${width}`, exact: true }).click()
    await page.goto(`/admin/alerts?project=${projectId}`)
    await expect(page.locator('.alert-event-row')).toHaveCount(3)
    await expect(page.locator('.notice-item')).toHaveCount(0)
    expect((await context.request.post(`${endpoint}/missed`)).ok()).toBe(true)
    await expect(page.locator('.notice-item')).toHaveCount(0)
    expect((await context.request.post(`${endpoint}/resumed`)).ok()).toBe(true)
    await expect(page.locator('.notice-item')).toHaveCount(1)
    await expect(page.locator('.alert-event-row')).toHaveCount(4)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

    await page.getByRole('button', { name: '切换项目', exact: true }).click()
    await expect(page.locator('.notice-item')).toHaveCount(0)
    expect((await context.request.post(`${endpoint}/late`)).ok()).toBe(true)
    await expect(page.locator('.notice-item')).toHaveCount(0)
    expect(videoRequests).toEqual([])
    expect(errors).toEqual([])
  })
}
