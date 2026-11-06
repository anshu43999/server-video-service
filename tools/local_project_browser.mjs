// Built UI + real HTTP APIs only: no route.fulfill or mock handlers.
import { chromium, expect } from '../admin-web/node_modules/@playwright/test/index.mjs'

const baseURL = process.env.LOCAL_ACCEPTANCE_URL
const target = new URL(baseURL)
if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1' || !target.port || target.username || target.password) throw new Error('local loopback URL required')
const browser = await chromium.launch({ executablePath: process.env.LOCAL_ACCEPTANCE_CHROME })
const password = 'local-acceptance-only-password'
const errors = []
const checks = {}
async function login(username) {
  const context = await browser.newContext({ baseURL })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.name))
  await page.goto('/admin/projects')
  await page.getByLabel('账号', { exact: true }).fill(username)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).not.toHaveURL(/login/)
  return { context, page }
}
try {
  const { page: adminPage } = await login('local-admin')
  await adminPage.goto('/admin/platform/projects')
  await expect(adminPage.getByRole('article', { name: '本地验收项目 A', exact: true })).toBeVisible()
  await expect(adminPage.getByRole('article', { name: '本地验收项目 B', exact: true })).toBeVisible()
  checks.platformSeesBothProjects = true
  const { context: owner, page: ownerPage } = await login('local-owner-a')
  const directory = await owner.request.get('/aiyoloapi/auth/projects')
  expect(directory.status()).toBe(200)
  const project = (await directory.json()).projects[0]
  await ownerPage.goto('/admin/members?project=' + project.projectId)
  await expect(ownerPage.getByRole('heading', { name: '项目成员管理' })).toBeVisible()
  await expect(ownerPage.getByRole('article', { name: 'local-user-a', exact: true })).toBeVisible()
  await expect(ownerPage.getByRole('link', { name: '平台账号', exact: true })).toHaveCount(0)
  checks.ownerMemberPage = true
  const { context: user, page: userPage } = await login('local-user-a')
  await userPage.goto('/admin/streams?project=' + project.projectId)
  await expect(userPage.getByRole('heading', { name: '视频流', exact: true })).toBeVisible()
  await expect(userPage.getByRole('link', { name: '平台账号', exact: true })).toHaveCount(0)
  expect((await user.request.post('/aiyoloapi/projects/' + project.projectId + '/streams', {
    data: { stream_id: 'forbidden-browser-write' },
  })).status()).toBe(403)
  checks.userReadOnlyServerEnforced = true
  await userPage.reload()
  await expect(userPage.getByRole('heading', { name: '视频流', exact: true })).toBeVisible()
  await userPage.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => userPage.locator('.sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  expect(await userPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await userPage.screenshot({ path: '../evidence/M33/M33-T18-local-user-390.png', fullPage: true, animations: 'disabled' })
  await ownerPage.screenshot({ path: '../evidence/M33/M33-T18-local-owner.png', fullPage: true, animations: 'disabled' })
  await adminPage.screenshot({ path: '../evidence/M33/M33-T18-local-platform.png', fullPage: true, animations: 'disabled' })
  checks.refreshAndNarrowViewport = true
  expect(errors).toEqual([])
  console.log(JSON.stringify(checks))
} finally {
  await browser.close()
}
