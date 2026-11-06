import { expect, test } from '@playwright/test'
import { selectElementOption } from './helpers/navigation'

test.beforeEach(({}, info) => test.skip(info.project.name !== 'production-chromium', 'requires isolated real backend'))

for (const width of [1440, 390]) {
  test(`suite member inputs, plan editing, approval and role visibility at ${width}px`, async ({ context, page, browser }) => {
    test.setTimeout(90_000)
    expect((await context.request.post('/aiyoloapi/auth/login', {
      data: { username: `business-owner-scene${width}`, password: 'business-test-password' },
    })).ok()).toBe(true)
    const projects = (await (await context.request.get('/aiyoloapi/auth/projects')).json()).projects
    const projectId = projects[0].projectId
    const base = `/aiyoloapi/projects/${projectId}/scenes/site-safety`

    await page.setViewportSize({ width, height: 960 })
    await page.goto(`/admin/scenes?project=${projectId}`)
    await expect(page.getByRole('heading', { name: '识别场景', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '创建场景', exact: true }).click()
    await page.getByLabel('场景 ID', { exact: true }).fill('site-safety')
    await page.getByLabel('场景名称', { exact: true }).fill('现场安全套件')

    await selectElementOption(page, '项目模型', '安全帽检测 / 1.0.0 · PC 端', false)
    await page.getByRole('button', { name: '添加项目模型成员' }).click()
    await selectElementOption(page, '项目模型', '安全帽检测 / 2.0.0 · PC 端', false)
    await page.getByRole('button', { name: '添加项目模型成员' }).click()
    const members = page.locator('.scene-members.editable > li')
    await expect(members).toHaveCount(2)
    await expect(page.locator('.scene-capability-summary').filter({ hasText: '当前套件能力' })).toContainText('图片')
    await expect(page.locator('.scene-capability-summary').filter({ hasText: '当前套件能力' })).toContainText('本机相机连续帧')

    // A single-member image plan remains runnable as a configuration; a two-member
    // plan is accepted only as an explicit, non-executable sync declaration.
    const draft = page.locator('.scene-plan-draft')
    const planOptions = draft.locator('.scene-plan-options')
    await draft.getByLabel('方案 ID', { exact: true }).fill('image-safety')
    await draft.getByLabel('方案名称', { exact: true }).fill('静态识别')
    await planOptions.nth(1).locator('label.model-check').nth(0).click()
    await page.getByRole('button', { name: '添加运行方案' }).click()

    await draft.getByLabel('方案 ID', { exact: true }).fill('combined-safety')
    await draft.getByLabel('方案名称', { exact: true }).fill('联合识别')
    await planOptions.nth(1).locator('label.model-check').nth(0).click()
    await planOptions.nth(1).locator('label.model-check').nth(1).click()
    await selectElementOption(page, '执行方式', '同步（仅配置）')
    await page.getByRole('button', { name: '添加运行方案' }).click()
    await expect(page.getByText('多模型方案当前仅配置，不可运行')).toBeVisible()

    await page.getByRole('button', { name: '保存新场景', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    let scene = await (await context.request.get(base)).json()
    expect(scene.models).toHaveLength(2)
    expect(scene.plans.map((plan: any) => plan.planId).sort()).toEqual(['combined-safety', 'image-safety'])
    expect(scene.plans.find((plan: any) => plan.planId === 'combined-safety')).toMatchObject({ execution: 'sync' })

    await page.getByRole('button', { name: '批准场景 现场安全套件', exact: true }).click()
    await page.getByLabel('审核原因').fill('已核验隔离套件成员与方案配置')
    await page.getByRole('button', { name: '确认批准', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    scene = await (await context.request.get(base)).json()
    expect(scene).toMatchObject({ revision: 2, approved: true, executionSupported: false })
    expect((await context.request.post(`${base}/resolve`, {
      data: { expectedRevision: 2, target: 'pc', inputType: 'image' },
    })).status()).toBe(409)
    expect((await context.request.post(`${base}/plans/combined-safety/resolve`, {
      data: { planId: 'combined-safety', expectedRevision: 2, target: 'pc', inputType: 'image', clientContractVersion: 2 },
    })).status()).toBe(409)
    await page.getByRole('button', { name: '查看详情 现场安全套件', exact: true }).click()
    await expect(page.locator('.scene-plan-summary')).toContainText('已配置 · 客户端未支持')
    await expect(page.locator('.scene-plan-summary')).toContainText('可使用 · 需在线预检')
    const profileButton=page.getByRole('button',{name:/^配置待审参数 /}).first()
    await profileButton.click()
    await expect(page.getByRole('dialog',{name:'场景详情',exact:true})).toHaveCount(0)
    const profileDialog=page.getByRole('dialog',{name:'模型参数档案',exact:true})
    await expect(profileDialog).toContainText('该场景成员的独立运行参数')
    await page.getByLabel('识别置信度',{exact:true}).fill('0.21')
    await page.getByRole('button',{name:'保存参数',exact:true}).click()
    await expect(profileDialog).toContainText('请重新审批该场景后运行')
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    scene=await(await context.request.get(base)).json()
    expect(scene).toMatchObject({revision:3,approved:false})
    expect(scene.models[0].parameterSnapshot.detection.confidenceThreshold).toBe(0.21)
    await page.getByRole('button',{name:'批准场景 现场安全套件',exact:true}).click()
    await expect(page.getByRole('dialog',{name:'审核场景可用性',exact:true})).toContainText('待审修订 1')
    await page.getByLabel('审核原因').fill('重新核对项目参数快照')
    await page.getByRole('button',{name:'确认批准',exact:true}).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    scene=await(await context.request.get(base)).json()
    expect(scene).toMatchObject({revision:4,approved:true})
    expect(scene.models[0].parameterSnapshot.detection.confidenceThreshold).toBe(0.21)
    expect((await context.request.post(`${base}/plans/combined-safety/resolve`,{data:{planId:'combined-safety',expectedRevision:2,target:'pc',inputType:'image',clientContractVersion:3,supportedExecutionModes:['sync']}})).status()).toBe(409)
    const v3=await context.request.post(`${base}/plans/combined-safety/resolve`,{data:{planId:'combined-safety',expectedRevision:4,target:'pc',inputType:'image',clientContractVersion:3,supportedExecutionModes:['sync']}})
    expect(v3.ok()).toBe(true);expect((await v3.json()).members).toHaveLength(2)
    await page.getByRole('button', { name: '查看详情 现场安全套件', exact: true }).click()
    await page.locator('.scene-approved-parameters summary').first().click()
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({path:`../evidence/M33/M33-T54/details-${width}.png`,fullPage:true,animations:'disabled'})
    await page.keyboard.press('Escape')

    const userContext = await browser.newContext({ baseURL: 'http://127.0.0.1:4174', viewport: { width, height: 960 } })
    try {
      expect((await userContext.request.post('/aiyoloapi/auth/login', {
        data: { username: `business-user-scene${width}`, password: 'business-test-password' },
      })).ok()).toBe(true)
      const user = await userContext.newPage()
      await user.goto(`/admin/scenes?project=${projectId}`)
      await expect(user.getByRole('button', { name: '查看详情 现场安全套件', exact: true })).toBeVisible()
      await user.getByRole('button', { name: '查看详情 现场安全套件', exact: true }).click()
      await expect(user.getByRole('button', { name: '创建场景', exact: true })).toHaveCount(0)
      await expect(user.getByRole('button', { name: /批准场景|撤销批准/ })).toHaveCount(0)
      await expect(user.locator('.scene-plan-summary')).toContainText('同步（仅配置）')
      expect(await user.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

      await page.getByRole('button', { name: '编辑场景 现场安全套件', exact: true }).click()
      await page.getByRole('button', { name: '编辑方案 静态识别', exact: true }).click()
      await draft.getByLabel('方案名称', { exact: true }).fill('静态图片识别')
      const updatePlan = page.getByRole('button', { name: '更新方案', exact: true })
      await updatePlan.focus()
      await page.keyboard.press('Enter')
      const saveChanges = page.getByRole('button', { name: '保存场景变更', exact: true })
      await saveChanges.focus()
      await page.keyboard.press('Enter')
      await expect(page.getByRole('dialog')).toHaveCount(0)
      scene = await (await context.request.get(base)).json()
      expect(scene).toMatchObject({ revision: 5, approved: false })
      expect(scene.plans.find((plan: any) => plan.planId === 'image-safety').name).toBe('静态图片识别')
      await expect(page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).resolves.toBe(true)
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({ path: `../evidence/M33/M33-T54/edited-${width}.png`, fullPage: true, animations: 'disabled' })

      // Project users lose visibility as soon as an edit invalidates approval.
      await user.reload()
      await expect(user.getByText('暂无可见场景', { exact: true })).toBeVisible()
      expect((await userContext.request.get(base)).status()).toBe(404)
    } finally {
      await userContext.close()
    }

    // The platform administrator can at least enter the project-scoped suite
    // view; business approval remains an explicit action by an authorized owner.
    const adminContext = await browser.newContext({ baseURL: 'http://127.0.0.1:4174', viewport: { width, height: 960 } })
    try {
      expect((await adminContext.request.post('/aiyoloapi/auth/login', {
        data: { username: 'cutover-admin', password: 'cutover-test-password' },
      })).ok()).toBe(true)
      const projectsResponse = await adminContext.request.get('/aiyoloapi/auth/projects')
      expect(projectsResponse.ok()).toBe(true)
      const adminPage = await adminContext.newPage()
      await adminPage.goto(`/admin/scenes?project=${projectId}`)
      await expect(adminPage.getByRole('heading', { name: '识别场景', exact: true })).toBeVisible()
    } finally {
      await adminContext.close()
    }
  })
}
