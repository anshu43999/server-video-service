import { expect, test } from '@playwright/test'
import { fixtureProject, fixtureUser, unscopedPath } from './helpers/project-fixture'
import { adminPath } from './helpers/navigation'

for (const width of [1440, 390]) {
  test(`uninstalled project model remains identifiable and explains activation at ${width}px`, async ({ context, page }, info) => {
    let writes = 0
    const errors: string[] = []
    const retainedName = '安全帽检测历史版 / HelmetInspectionModelWithoutSpaces'.repeat(2)
    const assignments = ['pc', 'mobile'].flatMap(target => ['UNINSTALLED', 'UNINSTALLED', 'MISSING'].map((modelStatus, index) => ({
      projectModelId: `retired-${target}-${index}`, projectId: fixtureProject.projectId,
      modelId: `uploaded-historical-${index}`, modelVersion: '2.0.0', target,
      parameterPlatform: target === 'pc' ? 'server' : 'android', parameterRevision: 0,
      parameterPublished: false, enabled: false, revision: 2, modelStatus,
      modelName: index === 0 ? retainedName : '未命名模型',
    })))
    page.on('pageerror', error => errors.push(error.message))
    await context.routeWebSocket('**/aiyoloapi/**', () => {})
    await context.route('**/aiyoloapi/**', async route => {
      if (route.request().method() !== 'GET') { writes++; await route.abort(); return }
      const path = unscopedPath(new URL(route.request().url()).pathname)
      const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
      if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: fixtureUser() })
      if (path.endsWith('/auth/me')) return reply(fixtureUser())
      if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [fixtureProject] })
      if (path === '/aiyoloapi') return reply(fixtureProject)
      if (path.endsWith('/model-assignments')) return reply({ assignments })
      if (path.endsWith('/models') || path.endsWith('/models/available')) return reply({ models: [] })
      return reply({}, 404)
    })
    await page.setViewportSize({ width, height: 960 })
    await page.goto(adminPath('/project-models'))
    for (const target of ['pc', 'mobile']) {
      await page.locator(`#project-model-tab-${target}`).click()
      const rows = page.locator('.inventory-row')
      await expect(rows).toHaveCount(3)
      await expect(rows.nth(0).locator('h4')).toHaveText(retainedName)
      await expect(rows.nth(1).locator('h4')).toHaveText('已卸载模型（历史名称未留存）')
      await expect(rows.nth(2).locator('h4')).toHaveText('模型版本已不可用')
      for (const row of await rows.all()) {
        await expect(row.getByRole('button', { name: '重新启用', exact: true })).toBeDisabled()
        await expect(row.getByRole('button', { name: '移除', exact: true })).toBeEnabled()
        await expect(row.locator('.inventory-unavailable')).toContainText('不能重新启用')
        const geometry = await row.evaluate(element => {
          const reason = element.querySelector('.inventory-unavailable')!.getBoundingClientRect()
          const actions = element.querySelector('.inventory-actions')!.getBoundingClientRect()
          return { gap: reason.top - actions.bottom, overflow: element.scrollWidth > element.clientWidth + 1 }
        })
        expect(geometry.gap).toBeGreaterThanOrEqual(8)
        expect(geometry.overflow).toBe(false)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await rows.first().getByRole('button', { name: '移除', exact: true }).click()
      const confirm = page.getByRole('alertdialog', { name: '移除项目模型', exact: true })
      await expect(confirm).toContainText(retainedName)
      await confirm.getByRole('button', { name: '取消', exact: true }).click()
      await expect(confirm).toHaveCount(0)
      await page.screenshot({ path: info.outputPath(`inventory-${target}-${width}.png`), animations: 'disabled' })
    }
    expect(writes).toBe(0)
    expect(errors).toEqual([])
    console.log(JSON.stringify({ width, browser: context.browser()!.version(), targets: ['pc', 'mobile'], rowsPerTarget: 3, writes, errors }))
  })
}
