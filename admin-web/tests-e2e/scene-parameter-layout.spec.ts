import { expect, test, type Locator } from '@playwright/test'
import { fixtureProject, fixtureUser, unscopedPath } from './helpers/project-fixture'
import { adminPath } from './helpers/navigation'

async function layoutMetrics(status: Locator) {
  return status.evaluate(element => {
    const rect = (selector: string) => element.querySelector(selector)!.getBoundingClientRect()
    const notice = rect('.scene-parameter-notice'), actions = rect('.scene-parameter-actions')
    const copy = rect('.scene-parameter-refresh-copy'), button = rect('.scene-parameter-actions button')
    const stacked = button.top >= copy.bottom
    return {
      separation: actions.top - notice.bottom,
      actionGap: stacked ? button.top - copy.bottom : button.left - copy.right,
      stacked,
      overflow: [...element.querySelectorAll<HTMLElement>('.scene-parameter-notice,.scene-parameter-models,.scene-parameter-models li,.scene-parameter-actions,.scene-parameter-refresh-copy')]
        .some(node => node.scrollWidth > node.clientWidth + 1),
    }
  })
}

for (const width of [1440, 768, 390, 320]) {
  test(`parameter guidance and refresh controls stay separated at ${width}px`, async ({ context, page }, info) => {
    const project = { ...fixtureProject, capabilities: [...fixtureProject.capabilities, 'project.scenes.manage'] }
    let published = false, longNames = false, writes = 0, modelReads = 0
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    // The app shell subscribes to alerts independently of this scene dialog.
    // Leave the mocked socket open without connecting it to the live backend.
    await context.routeWebSocket('**/aiyoloapi/**', () => {})
    const models = () => Array.from({ length: longNames ? 6 : 3 }, (_, index) => {
      const target = index === 1 ? 'mobile' : 'pc'
      const modelId = `layout-model-${index}`
      const version = index === 0 ? '2.0.0' : '1.0.0'
      const assignment = { projectModelId: `layout-pm-${index}`, modelId, modelVersion: version, target,
        parameterPlatform: target === 'mobile' ? 'android' : 'server', parameterRevision: 0,
        parameterPublished: published, enabled: true, revision: 1 }
      return { modelId, version, name: longNames ? 'PPE_SafetyInspectionModelWithoutSpaces'.repeat(4) : index === 0 ? 'helmet' : 'ppe',
        inputTypes: ['image', 'video'], assignment, assignments: [assignment], effectiveParametersByTarget: {} }
    })
    await context.route('**/aiyoloapi/**', async route => {
      if (route.request().method() !== 'GET') { writes++; await route.abort(); return }
      const path = unscopedPath(new URL(route.request().url()).pathname)
      const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
      if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: fixtureUser() })
      if (path.endsWith('/auth/me')) return reply(fixtureUser())
      if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [project] })
      if (path === '/aiyoloapi') return reply(project)
      if (path.endsWith('/scenes')) return reply({ scenes: [] })
      if (path.endsWith('/models')) { modelReads++; return reply({ models: models() }) }
      return reply({}, 404)
    })
    await page.setViewportSize({ width, height: 960 })
    await page.goto(adminPath('/scenes'))
    await page.getByRole('button', { name: '创建场景', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '创建项目场景', exact: true })
    const status = dialog.getByRole('region', { name: '项目模型参数状态' })
    await expect(status.locator('.scene-parameter-models li')).toHaveCount(3)
    await expect(status).toContainText('移动端（Android）')
    await expect(status).toContainText('PC 端（服务端）')
    const initial = await layoutMetrics(status)
    expect(initial.separation).toBeGreaterThanOrEqual(11)
    expect(initial.actionGap).toBeGreaterThanOrEqual(11)
    expect(initial.overflow).toBe(false)
    if (width <= 600) expect(initial.stacked).toBe(true)
    expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: info.outputPath(`notice-${width}.png`), animations: 'disabled' })

    await dialog.getByRole('button', { name: '高级设置（可选）', exact: true }).click()
    await dialog.getByLabel('场景 ID', { exact: true }).fill('layout-only-draft')
    await dialog.getByLabel('场景名称', { exact: true }).fill('保留这份未提交草稿')
    const refresh = status.getByRole('button', { name: '刷新项目模型状态', exact: true })
    longNames = true
    await refresh.focus(); await page.keyboard.press('Enter')
    await expect(status.locator('.scene-parameter-models li')).toHaveCount(6)
    const long = await layoutMetrics(status)
    expect(long.actionGap).toBeGreaterThanOrEqual(11)
    expect(long.overflow).toBe(false)
    expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true)
    await expect(dialog.getByLabel('场景 ID', { exact: true })).toHaveValue('layout-only-draft')
    await expect(dialog.getByLabel('场景名称', { exact: true })).toHaveValue('保留这份未提交草稿')

    published = true
    await refresh.click()
    await expect(status.locator('.scene-parameter-notice')).toHaveCount(0)
    await expect(status.getByText('项目模型状态', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('场景 ID', { exact: true })).toHaveValue('layout-only-draft')
    expect(modelReads).toBe(3)
    expect(writes).toBe(0)
    expect(errors).toEqual([])
    console.log(JSON.stringify({ width, browser: context.browser()!.version(), initial, long, modelReads, writes }))
  })
}
