import { expect, test, type Locator } from '@playwright/test'
import { fixtureProject, fixtureUser, unscopedPath } from './helpers/project-fixture'
import { adminPath, selectElementOption } from './helpers/navigation'
import type { Assignment, AssignmentWrite } from '../src/features/models/projectApi'

const makeAssignment = (modelVersion: string, enabled: boolean, revision: number, target: 'pc' | 'mobile' = 'pc'): Assignment => ({
  projectModelId: `pm-${modelVersion}-${target}`, projectId: fixtureProject.projectId,
  modelId: 'helmet', modelVersion, enabled, revision, target,
  parameterPlatform: target === 'pc' ? 'server' : 'android', parameterRevision: 4, parameterPublished: true,
})
const profile = (version: string, platform: 'server' | 'android') => ({
  schemaVersion: 2, modelId: 'helmet', modelVersion: version, platform, source: 'platform', revision: 4,
  detection: { confidenceThreshold: .3, iouThreshold: .45, maxDetections: 100 }, alertRules: [],
})
const model = (version: string) => ({
  modelId: 'helmet', version, name: '安全帽检测', status: 'PUBLISHED', releaseEligible: true,
  supportedTargets: ['pc', 'mobile'], serverReady: true, androidReady: true,
  targetReleaseEligible: { pc: true, mobile: true }, artifacts: [],
  parameterProfiles: { server: profile(version, 'server'), android: profile(version, 'android') },
})

async function checkLayout(dialog: Locator) {
  const metrics = await dialog.evaluate(element => {
    const preview = element.querySelector<HTMLElement>('.assignment-preview')!
    const footer = element.querySelector('form footer')!.getBoundingClientRect()
    const bottom = preview.getBoundingClientRect().bottom
    return {
      overflow: [...element.querySelectorAll<HTMLElement>('form,.assignment-preview,.el-dialog__body')]
        .filter(node => node.scrollWidth > node.clientWidth + 1).map(node => node.className),
      footerGap: footer.top - bottom,
      pageOverflow: document.documentElement.scrollWidth > innerWidth,
    }
  })
  expect(metrics.overflow).toEqual([])
  expect(metrics.pageOverflow).toBe(false)
  expect(metrics.footerGap).toBeGreaterThanOrEqual(0)
  return metrics
}

for (const width of [1440, 390]) {
  test(`prevents duplicates and distinguishes reactivation at ${width}px`, async ({ context, page }, info) => {
    let assignments = [makeAssignment('1.0', true, 3), makeAssignment('2.0', false, 8)]
    const writes: AssignmentWrite[] = [], errors: string[] = [], unexpected: string[] = [], metrics: unknown[] = []
    page.on('pageerror', error => errors.push(error.message))
    await context.routeWebSocket('**/aiyoloapi/**', () => {})
    await context.route('**/aiyoloapi/**', async route => {
      const request = route.request(), path = unscopedPath(new URL(request.url()).pathname)
      const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
      if (request.method() === 'PUT' && path.endsWith('/model-assignments')) {
        const value = request.postDataJSON() as AssignmentWrite
        writes.push(value)
        const previous = assignments.find(row => row.modelId === value.modelId && row.modelVersion === value.modelVersion && row.target === value.target)
        if ((previous?.revision ?? 0) !== value.expectedRevision) return reply({ detail: 'revision conflict' }, 409)
        const next = { ...makeAssignment(value.modelVersion, value.enabled, value.expectedRevision + 1, value.target) }
        assignments = previous ? assignments.map(row => row.projectModelId === previous.projectModelId ? next : row) : [...assignments, next]
        return reply(next)
      }
      if (request.method() !== 'GET') { unexpected.push(`${request.method()} ${path}`); return route.abort() }
      if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: fixtureUser() })
      if (path.endsWith('/auth/me')) return reply(fixtureUser())
      if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [fixtureProject] })
      if (path === '/aiyoloapi') return reply(fixtureProject)
      if (path.endsWith('/model-assignments')) return reply({ assignments })
      if (path.endsWith('/models/available')) return reply({ models: ['1.0', '2.0', '3.0'].map(model) })
      if (path.endsWith('/models')) return reply({ models: assignments.map(row => ({ ...model(row.modelVersion), assignment: row })) })
      return reply({}, 404)
    })
    await page.setViewportSize({ width, height: 960 })
    await page.goto(adminPath('/project-models'))
    const open = async () => {
      await page.getByRole('button', { name: '添加 PC 模型', exact: true }).click()
      await expect(page.getByRole('combobox', { name: /^模型版本(?:\s|$)/ })).toBeVisible()
    }
    await open()
    await selectElementOption(page, '模型版本', '安全帽检测 / 1.0（PC 端已添加）')
    let dialog = page.getByRole('dialog', { name: '分配项目模型', exact: true })
    await expect(dialog.locator('.assignment-preview')).toContainText('已添加 · r3')
    await expect(dialog.getByRole('status')).toContainText('无需重复添加')
    await expect(dialog.getByRole('button', { name: '已添加', exact: true })).toBeDisabled()
    metrics.push({ state: 'already-added', ...await checkLayout(dialog) })
    await page.screenshot({ path: info.outputPath(`already-added-${width}.png`), animations: 'disabled' })
    expect(writes).toHaveLength(0)

    // Same exact release on another target remains independently assignable.
    await selectElementOption(page, '启用目标端', '移动端')
    await expect(dialog.locator('.assignment-preview')).toContainText('尚未添加')
    await dialog.getByRole('button', { name: '确认分配', exact: true }).click()
    let confirmation = page.getByRole('alertdialog', { name: '确认加入项目模型池', exact: true })
    await confirmation.getByRole('button', { name: '取消', exact: true }).click()
    await expect(confirmation).toHaveCount(0)
    expect(writes).toHaveLength(0)
    await dialog.getByRole('button', { name: '确认分配', exact: true }).click()
    confirmation = page.getByRole('alertdialog', { name: '确认加入项目模型池', exact: true })
    await confirmation.getByRole('button', { name: '确认分配', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes).toEqual([{ modelId: 'helmet', modelVersion: '1.0', target: 'mobile', enabled: true, expectedRevision: 0 }])
    expect(assignments.find(row => row.projectModelId === 'pm-1.0-pc')?.revision).toBe(3)
    expect(assignments).toHaveLength(3)

    // Reopening recognizes the newly added target and blocks another addition.
    await open()
    await selectElementOption(page, '模型版本', '安全帽检测 / 1.0（PC 端已添加）')
    await selectElementOption(page, '启用目标端', '移动端（已添加）')
    await expect(dialog.getByRole('button', { name: '已添加', exact: true })).toBeDisabled()
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    expect(writes).toHaveLength(1)

    // A disabled release is reactivated in place using its original revision.
    await open()
    await selectElementOption(page, '模型版本', '安全帽检测 / 2.0（PC 端已停用，可重新启用）')
    dialog = page.getByRole('dialog', { name: '重新启用项目模型', exact: true })
    await expect(dialog.locator('.assignment-preview')).toContainText('已停用 · r8')
    await expect(dialog.getByRole('status')).toContainText('不新增重复条目')
    metrics.push({ state: 'reactivating', ...await checkLayout(dialog) })
    await page.screenshot({ path: info.outputPath(`reactivating-${width}.png`), animations: 'disabled' })
    await dialog.getByRole('button', { name: '重新启用', exact: true }).click()
    confirmation = page.getByRole('alertdialog', { name: '确认重新启用项目模型', exact: true })
    await expect(confirmation).toContainText('保留原项目模型条目')
    await confirmation.getByRole('button', { name: '取消', exact: true }).click()
    await expect(confirmation).toHaveCount(0)
    expect(writes).toHaveLength(1)
    await dialog.getByRole('button', { name: '重新启用', exact: true }).click()
    await confirmation.getByRole('button', { name: '确认重新启用', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[1]).toEqual({ modelId: 'helmet', modelVersion: '2.0', target: 'pc', enabled: true, expectedRevision: 8 })
    expect(assignments.find(row => row.projectModelId === 'pm-2.0-pc')).toMatchObject({ revision: 9, enabled: true })
    expect(assignments).toHaveLength(3)

    // A new version remains independently assignable in the same target pool.
    await open()
    await selectElementOption(page, '模型版本', '安全帽检测 / 3.0')
    dialog = page.getByRole('dialog', { name: '分配项目模型', exact: true })
    await expect(dialog.locator('.assignment-preview')).toContainText('尚未添加')
    await dialog.getByRole('button', { name: '确认分配', exact: true }).click()
    await page.getByRole('alertdialog', { name: '确认加入项目模型池', exact: true }).getByRole('button', { name: '确认分配', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[2]).toEqual({ modelId: 'helmet', modelVersion: '3.0', target: 'pc', enabled: true, expectedRevision: 0 })
    expect(assignments).toHaveLength(4)
    expect(errors).toEqual([]); expect(unexpected).toEqual([])
    console.log(JSON.stringify({ width, browser: context.browser()!.version(), writes, metrics, errors, unexpected }))
  })
}
