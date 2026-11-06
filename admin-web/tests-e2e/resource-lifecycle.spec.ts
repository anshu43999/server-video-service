import { expect, test } from '@playwright/test'

test.beforeEach(({}, info) => test.skip(info.project.name !== 'production-chromium', 'isolated real backend required'))
for (const width of [1440, 390]) {
  test(`scene deletion previews, confirms and preserves shared model assets at ${width}px`, async ({ page, context }) => {
    await context.request.post('/aiyoloapi/auth/login', { data: { username: `business-owner-lifecycle${width}`, password: 'business-test-password' } })
    const projectId = (await (await context.request.get('/aiyoloapi/auth/projects')).json()).projects[0].projectId
    const base = `/aiyoloapi/projects/${projectId}/scenes`
    for (const sceneId of ['suite-a','suite-b']) {
      const created = await context.request.post(base, { data: { sceneId, name: sceneId, inputTypes: ['image'], enabled: false, expectedRevision: 0, models: [{ memberId: 'helmet', modelId: 'helmet', version: '1.0.0', target: 'pc', position: 0, execution: 'single' }] } })
      expect(created.status()).toBe(201)
    }
    await page.setViewportSize({ width, height: 960 })
    await page.goto(`/admin/scenes?project=${projectId}`)
    await page.getByRole('button', { name: '删除场景', exact: true }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('不级联删除模型资产')
    await expect(dialog).toContainText('离线设备数量未知')
    const submit = dialog.getByRole('button', { name: '确认删除场景', exact: true })
    await expect(submit).toBeDisabled()
    await dialog.getByText('我已确认影响，执行云端软删除', { exact: true }).click()
    await expect(submit).toBeEnabled()
    await page.screenshot({ path: `../harness/evidence/M112/T02/scene-removal-${width}.png`, fullPage: true })
    const response = page.waitForResponse(r => r.request().method() === 'DELETE' && r.url().includes('/scenes/'))
    await submit.click()
    expect((await response).status()).toBe(200)
    await expect(dialog).toHaveCount(0)
    expect((await (await context.request.get(base)).json()).scenes).toHaveLength(1)
    const remaining = await context.request.get(base+'/suite-b')
    expect(remaining.ok()).toBe(true)
    expect((await remaining.json()).models[0].modelId).toBe('helmet')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}
test('model preview blocks dependencies and permits only an unreferenced exact version', async ({ page, context }) => {
  await context.request.post('/aiyoloapi/auth/login', { data: { username: 'cutover-admin', password: 'cutover-test-password' } })
  const projects = (await (await context.request.get('/aiyoloapi/auth/projects')).json()).projects
  const projectId = projects.find((p:any) => p.projectCode === 'business-security').projectId
  const scene = await context.request.post(`/aiyoloapi/projects/${projectId}/scenes`, { data: { sceneId: 'lifecycle-block', name: 'Blocked', inputTypes: ['image'], enabled: false, expectedRevision: 0, models: [{ memberId:'m', modelId:'helmet', version:'1.0.0', target:'pc', position:0, execution:'single' }] } })
  expect(scene.status()).toBe(201)
  await page.goto('/admin/models')
  const card = page.locator('.model-card').filter({ hasText: '安全帽检测' }).filter({ hasText: '1.0.0' }).first()
  await card.getByRole('button', { name:'卸载', exact:true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('当前存在依赖')
  await expect(dialog.getByRole('button',{name:'确认卸载',exact:true})).toBeDisabled()
  await dialog.getByRole('button',{name:'取消',exact:true}).click()
  const other = page.locator('.model-card').filter({ hasText:'双端验收模型' }).first()
  await other.getByRole('button',{name:'卸载',exact:true}).click()
  await expect(dialog).toContainText('不会远程擦除')
  await dialog.getByText('我已确认云端物理回收范围',{exact:true}).click()
  await page.screenshot({path:'../harness/evidence/M112/T02/model-removal.png',fullPage:true})
  const response = page.waitForResponse(r => r.request().method()==='DELETE' && r.url().includes('/models/dual/versions/1.0.0'))
  await dialog.getByRole('button',{name:'确认卸载',exact:true}).click()
  expect((await response).status()).toBe(200)
  await expect(dialog).toHaveCount(0)
  expect((await context.request.get('/aiyoloapi/models/helmet/versions/1.0.0')).ok()).toBe(true)
})
