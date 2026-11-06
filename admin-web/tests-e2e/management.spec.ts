import { expect, test, type Page, type BrowserContext } from '@playwright/test'
test.beforeEach(({}, info) => test.skip(info.project.name !== 'production-chromium', 'Requires isolated real management server'))
const password = 'management-test-password-1'
async function login(page: Page, username = 'cutover-admin', pass = 'cutover-test-password', target = '/admin/platform/projects') {
  await page.goto(target)
  await page.getByLabel('账号', { exact: true }).fill(username)
  await page.getByLabel('密码', { exact: true }).fill(pass)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '平台项目管理', exact: true })).toBeVisible()
}
async function account(context: BrowserContext, username: string) {
  const response = await context.request.post('/aiyoloapi/platform/accounts', { data: { username, password, platformRole: 'NORMAL_USER' } }); expect(response.status()).toBe(201); return response.json()
}
async function seed(context: BrowserContext, suffix: string) {
  const owner = await account(context, `owner-${suffix}`), member = await account(context, `member-${suffix}`)
  const response = await context.request.post('/aiyoloapi/platform/projects', { data: { projectCode: `site-${suffix}`, displayName: `现场 ${suffix}`, ownerAccountId: owner.accountId } }); expect(response.status()).toBe(201)
  const project = await response.json()
  const added = await context.request.post(`/aiyoloapi/projects/${project.projectId}/members`, { data: { accountId: member.accountId } }); expect(added.status()).toBe(201)
  return { project, owner, member }
}
for (const width of [1440, 390]) {
  test(`real account project membership lifecycle and audit at ${width}px`, async ({ context, page }) => {
    await page.setViewportSize({ width, height: 960 }); await login(page)
    const suffix = `${width}-${Date.now()}`, username = `owner-${suffix}`, projectName = `巡检项目 ${suffix}`
    await page.goto('/admin/platform/accounts'); await page.getByRole('button', { name: '创建账号', exact: true }).click()
    let dialog = page.getByRole('dialog')
    await dialog.getByLabel('账号名称').fill(username); await dialog.getByLabel('初始密码').fill(password)
    await dialog.getByRole('button', { name: '确认创建账号' }).click(); await expect(dialog).toHaveCount(0)
    const accountCard = page.getByRole('article', { name: username, exact: true }); await expect(accountCard).toContainText('已启用')
    await accountCard.getByRole('button', { name: '管理账号' }).click(); dialog = page.getByRole('dialog')
    await dialog.getByLabel('账号状态').selectOption({ label: '已停用' }); await expect(dialog).toContainText('将停止该账号访问所有项目')
    await dialog.getByRole('button', { name: '确认更新账号' }).click(); await expect(dialog).toHaveCount(0); await expect(accountCard).toContainText('已停用')
    await accountCard.getByRole('button', { name: '管理账号' }).click(); await page.getByLabel('账号状态').selectOption({ label: '已启用' }); await page.getByRole('button', { name: '确认更新账号' }).click(); await expect(page.getByRole('dialog')).toHaveCount(0)
    const member = await account(context, `member-${suffix}`)
    await page.goto('/admin/platform/projects'); await page.getByRole('button', { name: '创建项目', exact: true }).click()
    dialog = page.getByRole('dialog'); await dialog.getByLabel('项目名称').fill(projectName); await dialog.getByLabel('项目代码').fill(`site-${suffix}`)
    const owner = (await (await context.request.get('/aiyoloapi/platform/accounts')).json()).accounts.find((a: any) => a.username === username)
    await dialog.getByLabel('初始负责人').selectOption(owner.accountId); await dialog.getByRole('button', { name: '确认创建项目' }).click(); await expect(dialog).toHaveCount(0)
    let card = page.getByRole('article', { name: projectName, exact: true }); await card.getByRole('button', { name: '编辑项目' }).click()
    await page.getByLabel('项目名称').fill(`${projectName} 已更新`); await page.getByRole('button', { name: '确认编辑项目' }).click(); await expect(page.getByRole('dialog')).toHaveCount(0)
    card = page.getByRole('article', { name: `${projectName} 已更新`, exact: true })
    await card.getByRole('button', { name: '进入项目管理成员' }).click(); await expect(page.getByRole('heading', { name: '项目成员管理' })).toBeVisible()
    const projectId = new URL(page.url()).searchParams.get('project')!
    await page.getByRole('button', { name: '添加项目成员', exact: true }).click(); await page.getByLabel('选择账号').selectOption(member.accountId); await page.getByRole('button', { name: '确认添加项目成员' }).click(); await expect(page.getByRole('dialog')).toHaveCount(0)
    const memberCard = page.getByRole('article', { name: member.username, exact: true })
    await memberCard.getByRole('button', { name: '编辑成员' }).click(); await page.getByLabel('项目角色').selectOption('PROJECT_OWNER'); await page.getByRole('button', { name: '确认编辑项目成员' }).click(); await expect(page.getByRole('dialog')).toHaveCount(0); await expect(memberCard).toContainText('项目负责人')
    await memberCard.getByRole('button', { name: '编辑成员' }).click(); await page.getByLabel('项目角色').selectOption('PROJECT_USER'); await page.getByRole('button', { name: '确认编辑项目成员' }).click(); await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('article', { name: username, exact: true }).getByRole('button', { name: '移交负责人' }).click(); await page.getByLabel('接收负责人').selectOption(member.accountId); await page.getByRole('button', { name: '确认移交负责人' }).click(); await expect(page.getByRole('dialog')).toHaveCount(0); await expect(memberCard).toContainText('项目负责人')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `../evidence/M33/M33-T11-members-${width}.png`, fullPage: true })
    await page.goto(`/admin/project-audit?project=${projectId}`); await expect(page.locator('.audit-list')).toContainText('membership.transfer_owner'); await expect(page.locator('.audit-list')).toContainText('project.platform_entry')
    await page.goto('/admin/platform/projects')
    for (const [action, state] of [['停用项目', '已停用'], ['恢复项目', '运行中'], ['归档项目', '已归档'], ['恢复项目', '运行中']]) {
      card = page.getByRole('article', { name: `${projectName} 已更新`, exact: true }); await card.getByRole('button', { name: action, exact: true }).click()
      if (action === '归档项目') {
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
        await expect(page.getByRole('dialog')).toBeVisible()
        await page.screenshot({ path: `../evidence/M33/M33-T11-confirm-${width}.png`, animations: 'disabled' })
      }
      await page.getByRole('dialog').getByRole('button', { name: `确认${action}`, exact: true }).click(); await expect(page.getByRole('dialog')).toHaveCount(0); await expect(card).toContainText(state!)
    }
    await page.getByLabel('搜索项目').fill(`site-${suffix}`); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `../evidence/M33/M33-T11-platform-${width}.png`, fullPage: true })
    await page.screenshot({ path: `../evidence/M33/M33-T16-platform-${width}.png`, fullPage: true, animations: 'disabled' })
    await page.goto('/admin/platform/audit'); await expect(page.locator('.audit-list')).toContainText('account.'); await expect(page.locator('body')).not.toContainText(password)
  })
}

test('real owner can maintain only ordinary users, transfer self and immediately loses management', async ({ context, page, browser }) => {
  await login(page); const { project, owner, member } = await seed(context, `owner-flow-${Date.now()}`)
  const extra = await account(context, `extra-${Date.now()}`)
  const ownerContext = await browser.newContext({ baseURL: 'http://127.0.0.1:4174' })
  try {
    const ownerPage = await ownerContext.newPage(); await ownerPage.goto(`/admin/members?project=${project.projectId}`)
    await ownerPage.getByLabel('账号', { exact: true }).fill(owner.username); await ownerPage.getByLabel('密码', { exact: true }).fill(password); await ownerPage.getByRole('button', { name: '登录', exact: true }).click()
    await expect(ownerPage.getByRole('heading', { name: '项目成员管理' })).toBeVisible()
    expect((await ownerContext.request.get('/aiyoloapi/platform/accounts')).status()).toBe(403)
    await expect(ownerPage.getByRole('link', { name: '平台账号', exact: true })).toHaveCount(0)
    await expect(ownerPage.getByRole('article', { name: owner.username, exact: true }).getByRole('button', { name: '编辑成员' })).toHaveCount(0)
    await ownerPage.getByRole('button', { name: '添加项目成员', exact: true }).click(); await expect(ownerPage.getByLabel('项目角色', { exact: true })).toHaveCount(0)
    await ownerPage.getByLabel('已有平台账号 ID').fill(extra.accountId); await ownerPage.getByRole('button', { name: '确认添加项目成员' }).click(); await expect(ownerPage.getByRole('dialog')).toHaveCount(0)
    const extraCard = ownerPage.getByRole('article', { name: extra.username, exact: true })
    await extraCard.getByRole('button', { name: '编辑成员' }).click(); await ownerPage.getByLabel('成员状态').selectOption({ label: '停用' }); await ownerPage.getByRole('button', { name: '确认编辑项目成员' }).click(); await expect(ownerPage.getByRole('dialog')).toHaveCount(0); await expect(extraCard).toContainText('访问已停止')
    const remove = extraCard.getByRole('button', { name: '移除成员' })
    await remove.focus(); await ownerPage.keyboard.press('Enter'); await expect(ownerPage.getByRole('dialog')).toContainText('不删除平台账号或业务历史')
    await ownerPage.keyboard.press('Escape'); await expect(ownerPage.getByRole('dialog')).toHaveCount(0); await expect(extraCard).toBeVisible()
    await remove.click(); await ownerPage.getByRole('button', { name: '确认移除项目成员' }).click(); await expect(ownerPage.getByRole('dialog')).toHaveCount(0); await expect(extraCard).toHaveCount(0)
    const escalation = await ownerContext.request.patch(`/aiyoloapi/projects/${project.projectId}/members/${member.accountId}`, { data: { expectedRevision: 1, projectRole: 'PROJECT_OWNER' } }); expect(escalation.status()).toBe(403)
    await ownerPage.getByRole('article', { name: owner.username, exact: true }).getByRole('button', { name: '移交负责人' }).click(); await ownerPage.getByLabel('接收负责人').selectOption(member.accountId)
    await expect(ownerPage.getByRole('dialog')).toContainText('您将失去本项目维护权限'); await ownerPage.getByRole('button', { name: '确认移交负责人' }).click()
    await expect(ownerPage.getByRole('heading', { name: '项目成员管理' })).toHaveCount(0)
    expect((await ownerContext.request.get(`/aiyoloapi/projects/${project.projectId}/members`)).status()).toBe(403)
    await ownerPage.goto('/admin/platform/accounts'); await expect(ownerPage).toHaveURL(/\/admin\/projects/); await expect(ownerPage.getByRole('heading', { name: '平台账号管理' })).toHaveCount(0)
  } finally { await ownerContext.close() }
})

test('last owner protection and suspended maintenance remain usable; archive allows only audit', async ({ context, page }) => {
  await login(page); const { project, owner } = await seed(context, `safety-${Date.now()}`)
  await page.goto(`/admin/members?project=${project.projectId}`)
  await page.getByRole('article', { name: owner.username, exact: true }).getByRole('button', { name: '移除成员' }).click(); await page.getByRole('button', { name: '确认移除项目成员' }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('最后一位有效负责人'); await expect(page.getByRole('button', { name: '确认移除项目成员' })).toBeDisabled(); await page.keyboard.press('Escape')
  await context.request.post(`/aiyoloapi/platform/projects/${project.projectId}/suspend`, { data: { expectedRevision: 1 } })
  await page.reload(); await expect(page.getByRole('heading', { name: '项目成员管理' })).toBeVisible(); await expect(page.getByRole('button', { name: '添加项目成员', exact: true })).toBeEnabled()
  await context.request.post(`/aiyoloapi/platform/projects/${project.projectId}/archive`, { data: { expectedRevision: 2 } })
  await page.goto(`/admin/project-audit?project=${project.projectId}`); await expect(page.getByRole('heading', { level: 2, name: '项目审计' })).toBeVisible(); await expect(page.locator('.audit-list')).toContainText('project.archive')
  await expect(page.getByRole('link', { name: '项目成员', exact: true })).toHaveCount(0)
  expect((await context.request.get(`/aiyoloapi/projects/${project.projectId}/members`)).status()).toBe(403)
  await page.goto('/admin/platform/projects'); const card = page.getByRole('article', { name: project.displayName, exact: true }); await expect(card.getByRole('button', { name: '恢复项目' })).toBeEnabled(); await expect(card.getByRole('button', { name: '进入项目管理成员' })).toHaveCount(0)
})

test('audit pages use server cursors and recover from a failed page without exposing payloads', async ({ context, page }) => {
  await login(page); const value = await account(context, `audit-pages-${Date.now()}`)
  for (let index = 0; index < 27; index++) {
    const response = await context.request.patch(`/aiyoloapi/platform/accounts/${value.accountId}`, { data: { expectedRevision: index + 1, enabled: index % 2 === 1 } }); expect(response.status()).toBe(200)
  }
  await page.goto('/admin/platform/audit'); await expect(page.locator('.audit-entry')).toHaveCount(25)
  const first = (await page.locator('.audit-entry').first().textContent())!
  await page.getByRole('button', { name: '下一页' }).click(); await expect(page.getByText('第 2 页', { exact: true })).toBeVisible(); await expect(page.locator('.audit-entry').first()).not.toHaveText(first)
  await page.getByRole('button', { name: '上一页' }).click(); await expect(page.locator('.audit-entry').first()).toHaveText(first)
  await page.route('**/platform/audit?*', route => route.fulfill({ status: 503, json: { detail: 'audit unavailable' } }))
  await page.getByRole('button', { name: '刷新审计' }).click(); await expect(page.getByRole('alert')).toBeVisible(); await expect(page.locator('.audit-entry')).toHaveCount(0)
  await page.unroute('**/platform/audit?*'); await page.getByRole('button', { name: '刷新审计' }).click(); await expect(page.locator('.audit-entry')).toHaveCount(25); await expect(page.locator('body')).not.toContainText(password)
})

test('conflicts retain edits, prevent replay and recover after refresh; failed writes do not claim success', async ({ context, page }) => {
  await login(page); const { project } = await seed(context, `conflict-${Date.now()}`)
  await page.getByRole('button', { name: '刷新项目列表' }).click()
  const card = page.getByRole('article', { name: project.displayName, exact: true })
  await card.getByRole('button', { name: '编辑项目' }).click(); await page.getByLabel('项目名称').fill('待保留的草稿')
  await context.request.patch(`/aiyoloapi/platform/projects/${project.projectId}`, { data: { expectedRevision: 1, displayName: '其他管理员已更新' } })
  await page.getByRole('button', { name: '确认编辑项目' }).click(); await expect(page.getByRole('dialog').getByRole('alert')).toContainText('不会覆盖他人的更改'); await expect(page.getByLabel('项目名称')).toHaveValue('待保留的草稿'); await expect(page.getByRole('button', { name: '确认编辑项目' })).toBeDisabled()
  await page.getByRole('dialog').getByRole('button', { name: '取消' }).click(); await page.getByRole('button', { name: '刷新项目列表' }).click(); await expect(page.getByRole('article', { name: '其他管理员已更新', exact: true })).toBeVisible()
  await page.getByRole('article', { name: '其他管理员已更新', exact: true }).getByRole('button', { name: '编辑项目' }).click(); await page.getByLabel('项目名称').fill('再次提交的草稿')
  await page.route(`**/platform/projects/${project.projectId}`, route => route.fulfill({ status: 503, json: { detail: 'temporarily unavailable' } }))
  await page.getByRole('button', { name: '确认编辑项目' }).click(); await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible(); await expect(page.getByLabel('项目名称')).toHaveValue('再次提交的草稿'); await expect(page.locator('.management-success')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '确认编辑项目' })).toBeDisabled()
  await page.unroute(`**/platform/projects/${project.projectId}`); await page.getByRole('dialog').getByRole('button', { name: '取消' }).click(); await page.getByRole('button', { name: '刷新项目列表' }).click()
  await page.getByRole('article', { name: '其他管理员已更新', exact: true }).getByRole('button', { name: '编辑项目' }).click(); await page.getByLabel('项目名称').fill('再次提交的草稿'); await page.getByRole('button', { name: '确认编辑项目' }).click(); await expect(page.getByRole('dialog')).toHaveCount(0); await expect(page.getByRole('article', { name: '再次提交的草稿', exact: true })).toBeVisible()
})
