import { expect, test } from '@playwright/test'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'

for (const width of [1440, 390]) {
  test(`project platform parameter publication state at ${width}px`, async ({ context, page }, info) => {
    const project = { ...fixtureProject, projectRole: 'PROJECT_OWNER', membershipRevision: 1, platformEntry: false }
    const assignment = { projectModelId: 'pm-mobile', projectId: project.projectId, modelId: 'helmet', modelVersion: '1.0.0', target: 'mobile', parameterPlatform: 'android', parameterRevision: 0, parameterPublished: false, enabled: true, revision: 3 }
    const model = { modelId: 'helmet', name: '安全帽巡检', version: '1.0.0', status: 'PUBLISHED', supportedTargets: ['mobile'], androidReady: true, targetReleaseEligible: { mobile: true }, targetReadiness: { mobile: { ready: true } }, artifacts: [], assignment }
    let published = false
    const writes: string[] = []
    const reads: string[] = []
    await context.route('**/aiyoloapi/**', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname
      const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
      if (request.method() !== 'GET') writes.push(`${request.method()} ${path}`)
      if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: fixtureUser('operator') })
      if (path.endsWith('/auth/me')) return reply(fixtureUser('operator'))
      if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [project] })
      if (path.endsWith(`/projects/${project.projectId}`)) return reply(project)
      if (path.endsWith('/model-assignments')) return reply({ assignments: [{ ...assignment, parameterPublished: published }] })
      if (path.endsWith('/models')) return reply({ models: [model] })
      if (path.endsWith('/models/helmet/parameters')) {
        reads.push(url.pathname + url.search)
        if (!published) return reply({ detail: { code: 'platform_parameters_unpublished', message: 'platform parameters must be published before use' } }, 409)
        return reply({ schemaVersion: 2, modelId: 'helmet', modelVersion: '1.0.0', platform: 'android', source: 'platform', revision: 0, detection: { confidenceThreshold: .35, iouThreshold: .45, maxDetections: 100 }, alertRules: [], audit: [] })
      }
      if (path.endsWith('/alerts')) return reply({ events: [] })
      return reply({})
    })
    await context.routeWebSocket('**/aiyoloapi/**', socket => { socket.onMessage(() => {}) })
    await page.setViewportSize({ width, height: 960 })
    await page.goto(`/admin/project-models?project=${project.projectId}`)
    await page.getByRole('tab', { name: /移动端/ }).click()
    await expect(page.locator('.inventory-meta')).toContainText('尚未发布')
    await page.getByRole('button', { name: '查看平台参数', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '查看平台参数', exact: true })
    await expect(dialog).toContainText('平台参数尚未发布')
    await expect(dialog).toContainText('模型版本 1.0.0 的Android参数尚未发布')
    await expect(dialog).not.toContainText('数据不可用')
    await expect(dialog.getByRole('button', { name: '发布参数', exact: true })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: '重新读取档案', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: info.outputPath(`unpublished-${width}.png`), fullPage: true, animations: 'disabled' })
    published = true
    await dialog.getByRole('button', { name: '重新读取档案', exact: true }).click()
    await expect(dialog).toContainText('平台发布参数')
    await expect(dialog).not.toContainText('平台参数尚未发布')
    await expect(dialog.locator('.parameter-detection-values')).toContainText('识别置信度0.35')
    await expect(dialog.locator('input[type="number"],[role="switch"]')).toHaveCount(0)
    await expect(dialog).toContainText('当前参数档案未配置类别规则')
    expect(reads).toHaveLength(2)
    expect(reads.every(path => path === `/aiyoloapi/projects/${project.projectId}/models/helmet/parameters?platform=android&version=1.0.0`)).toBe(true)
    expect(writes).toEqual([])
  })
}
