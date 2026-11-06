import { expect, test, type BrowserContext } from '@playwright/test'
import { statsFixture } from '../tests/fixtures/dashboard'

test.beforeEach(({}, info) => {
  test.skip(info.project.name !== 'production-chromium', 'Requires built assets and isolated FastAPI hosting')
})

async function business(context: BrowserContext) {
  const unexpected: string[] = []
  await context.route('**/aiyoloapi/**', route => {
    const url = new URL(route.request().url()), path = url.pathname
    if (path.includes('/auth/') || (path.startsWith('/aiyoloapi/projects/') && path.split('/').length === 4)) return route.continue()
    const reply = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (path.endsWith('/dashboard/stats')) return reply(statsFixture())
    if (path.endsWith('/streams')) return reply([])
    if (path.endsWith('/alerts')) return reply({ events: [] })
    if (path.endsWith('/models')) return reply({ models: [] })
    if (path.endsWith('/rules')) return reply({ rules: [] })
    if (path.endsWith('/rules/audit')) return reply({ audit: [] })
    if (path.endsWith('/capabilities/sources')) return reply({ sources: [] })
    if (path.endsWith('/alerts/delivery/status')) return reply({ channels: {}, pending: 0, recent: [] })
    if (path.endsWith('/delivery/policy')) return reply({revision:0,enabled:true,channels:['management'],minimumSeverity:'MINOR'})
    if (path.endsWith('/verification/config')) return reply({ enabled: false, imageEgressAuthorized: false, dailyLimit: 100, callsToday: 0, modelId: '', providerConfigured: false })
    if (path.endsWith('/metrics')) return reply({ scope:'platform', system: { cpu_percent: 0, memory_percent: 20, gpu: null }, streams: {total:0,framesReceived:0,framesProcessed:0,framesDropped:0} })
    if (path.endsWith('/conversion/jobs')) return reply({ jobs: [] })
    if (path.endsWith('/conversion/calibration-datasets')) return reply({ datasets: [] })
    if (path.endsWith('/conversion/config')) return reply({ config: { mode: 'local', input_size: 640, timeout_seconds: 1800, auto_convert: false }, supported_modes: ['local'], max_upload_bytes: 1048576 })
    unexpected.push(path)
    return route.fulfill({ status: 404, body: 'unexpected fixture request' })
  })
  await context.route('**/healthz', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ status: 'ok', streams: 0, database: { configured: false, status: 'fallback' } }) }))
  return unexpected
}

const menus = [['overview', '总览'], ['dashboard', '数据看板'], ['streams', '视频流'], ['alerts', '告警中心'], ['push', '报警推送'], ['rules', '规则配置'], ['models', '模型资产'], ['diagnostics', '系统诊断'], ['verification', '智能复核']]

for (const width of [1440, 390]) {
  test(`production admin cookie login, all nine menus and refresh at ${width}px`, async ({ context, page }) => {
    test.setTimeout(90_000)
    const unexpected = await business(context), errors: string[] = [], assets: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', req => { if (new URL(req.url()).pathname.includes('/assets/')) assets.push(new URL(req.url()).pathname) })
    await page.setViewportSize({ width, height: 960 })
    await page.goto('/admin/rules')
    await expect(page).toHaveURL(/\/admin\/login\?redirect=/)
    await page.getByLabel('账号', { exact: true }).fill('cutover-admin')
    await page.getByLabel('密码', { exact: true }).fill('cutover-test-password')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.getByRole('button', { name: '进入 验收项目' }).click()
    await expect(page.getByRole('heading', { level: 1, name: '规则配置' })).toBeVisible()
    const projectId = new URL(page.url()).searchParams.get('project')!
    expect(projectId).toBeTruthy()
    const cookie = (await context.cookies()).find(cookie => cookie.name === 'aiyolo_session')
    expect(cookie?.httpOnly).toBe(true)
    for (const [path, title] of menus) {
      await page.goto(`/admin/${path}${['models', 'diagnostics'].includes(path!) ? '' : `?project=${projectId}`}`)
      await expect(page.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible()
      await page.reload()
      await expect(page.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await expect(page.locator('body')).not.toContainText('业务操作仍以旧版')
      await expect(page.getByRole('link', { name: /旧版/ })).toHaveCount(0)
      if (['overview', 'models', 'verification'].includes(path!)) {
        await page.screenshot({ path: `../evidence/M32/M32-T10-${path}-${width}.png`, fullPage: true })
      }
    }
    await page.goto('/admin/models?pane=calibration')
    await expect(page.getByRole('heading', { level: 3, name: '校准集版本' })).toBeVisible()
    await page.goto('/admin/models?pane=upload')
    await expect(page.locator('.ui-file-upload').filter({ has: page.getByLabel('训练权重 .pt') }).getByText('选择文件', { exact: true })).toBeVisible()
    await page.goto('/admin/page-that-does-not-exist')
    await expect(page.getByRole('heading', { level: 3, name: '页面不存在' })).toBeVisible()
    await page.getByRole('link', { name: '返回总览' }).click()
    await page.getByRole('button', { name: '进入 验收项目' }).click()
    await expect(page).toHaveURL(/\/admin\/overview[?]/)
    await page.getByRole('button', { name: '退出登录', exact: true }).click()
    await expect(page).toHaveURL(/\/admin\/login$/)
    expect(await page.evaluate(() => Object.keys(localStorage).filter(key => key !== 'aiyolo.session.changed').length + Object.keys(sessionStorage).length)).toBe(0)
    expect(assets.length).toBeGreaterThan(0)
    expect(assets.every(path => path.startsWith('/admin/assets/'))).toBe(true)
    expect(errors).toEqual([])
    expect(unexpected).toEqual([])
  })
}

test('real operator and anonymous sessions cannot read admin-only APIs or enter menus', async ({ context, page }) => {
  const requests: string[] = []
  page.on('request', request => requests.push(new URL(request.url()).pathname))
  const denied = await context.request.get('/aiyoloapi/rules')
  expect(denied.status()).toBe(401)
  await page.goto('/admin/models?pane=upload')
  await expect(page).toHaveURL(/\/admin\/login/)
  expect(requests.filter(path => path.startsWith('/aiyoloapi/') && !path.includes('/auth/'))).toEqual([])
  await page.getByLabel('账号', { exact: true }).fill('cutover-operator')
  await page.getByLabel('密码', { exact: true }).fill('cutover-test-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/projects/)
  await expect(page.getByRole('heading', { name: '暂无可访问项目' })).toBeVisible()
  for (const [path] of menus) {
    await page.goto(`/admin/${path}`)
    await expect(page).toHaveURL(/\/admin\/projects/)
  }
  expect((await context.request.get('/aiyoloapi/rules')).status()).toBe(403)
  expect((await context.request.get('/aiyoloapi/auth/me')).status()).toBe(200)
  expect(requests.filter(path => path.startsWith('/aiyoloapi/') && !path.includes('/auth/'))).toEqual([])
  await page.getByRole('button', { name: '退出登录' }).click()
  expect((await context.request.get('/aiyoloapi/auth/me')).status()).toBe(401)
})

test('retired resources are absent and both Vue bases stay independent', async ({ request }) => {
  const root = await request.get('/', { maxRedirects: 0 })
  expect(root.status()).toBe(307)
  expect(root.headers().location).toBe('/admin/')
  for (const name of ['index.html', 'styles.css', 'app.js', 'conversion.css', 'conversion.js']) {
    if (name === 'index.html') continue
    expect((await request.get(`/admin/${name}`)).status()).toBe(404)
  }
  expect((await request.get('/admin/evidence/evidence_helmet_violation.png')).status()).toBe(404)
  const preview = await request.get('/admin-next/overview', { headers: { accept: 'text/html' } })
  expect(preview.status()).toBe(200)
  expect(preview.headers()['cache-control']).toBe('no-cache')
  expect(await preview.text()).toContain('/admin-next/assets/')
  const stable = await request.get('/admin/overview', { headers: { accept: 'text/html' } })
  expect(stable.status()).toBe(200)
  expect(stable.headers()['cache-control']).toBe('no-cache')
  expect(await stable.text()).toContain('/admin/assets/')
  expect((await request.get('/admin/app.js')).status()).toBe(404)
})
