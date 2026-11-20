import { expect, test, type Locator } from '@playwright/test'
import { fixtureProject, fixtureUser, unscopedPath } from './helpers/project-fixture'
import { adminPath } from './helpers/navigation'

async function layoutMetrics(dialog: Locator) {
  return dialog.evaluate(element => {
    const selectors = '.parameter-content,.parameter-profile-meta,.parameter-detection-values,.parameter-readonly-toolbar,.parameter-readonly-rule,.parameter-rule-title,.parameter-rule-groups,.parameter-rule-group,.parameter-event-code,.parameter-readonly-audit'
    const overflow = [...element.querySelectorAll<HTMLElement>(selectors)]
      .filter(node => node.clientWidth > 0 && node.scrollWidth > node.clientWidth + 1)
      .map(node => node.className)
    const footer = element.querySelector('.parameter-readonly-actions')!
    const note = footer.querySelector('p')!.getBoundingClientRect()
    const button = footer.querySelector('button')!.getBoundingClientRect()
    const groups = element.querySelectorAll('.parameter-readonly-rule .parameter-rule-group')
    const first = groups[0]!.getBoundingClientRect(), second = groups[1]!.getBoundingClientRect()
    const name = element.querySelector('.parameter-rule-name')!.getBoundingClientRect()
    const badges = element.querySelector('.parameter-rule-badges')!.getBoundingClientRect()
    return {
      overflow,
      footerGap: button.top >= note.bottom ? button.top - note.bottom : button.left - note.right,
      groupsStacked: second.top >= first.bottom,
      groupGap: second.top >= first.bottom ? second.top - first.bottom : second.left - first.right,
      badgesSeparated: badges.top >= name.bottom - 1 || badges.left >= name.right - 1,
      dialogOverflow: element.scrollWidth > element.clientWidth + 1,
      bodyOverflow: element.querySelector('.el-dialog__body')!.scrollWidth > element.querySelector('.el-dialog__body')!.clientWidth + 1,
    }
  })
}

for (const width of [1440, 768, 390, 320]) {
  test(`project parameter details remain readable and read-only at ${width}px`, async ({ context, page }, info) => {
    const modelId = 'uploaded-parameter-layout-06b4dd2f10544673ab723226f91c34a7'
    const modelVersion = '2.0.0'
    const modelName = '安全帽与作业防护检测 / HelmetInspectionModelWithoutSpaces'.repeat(2)
    const assignments = (['pc', 'mobile'] as const).map(target => ({
      projectModelId: `parameter-${target}`, projectId: fixtureProject.projectId, modelId, modelVersion, target,
      parameterPlatform: target === 'pc' ? 'server' : 'android', parameterRevision: target === 'pc' ? 7 : 11,
      parameterPublished: true, enabled: true, revision: 3,
    }))
    const model = {
      modelId, version: modelVersion, name: modelName, status: 'PUBLISHED', supportedTargets: ['pc', 'mobile'],
      serverReady: true, serverBindable: true, androidReady: true, androidBindable: true,
      targetReadiness: { pc: { ready: true }, mobile: { ready: true } },
      artifacts: [], assignment: assignments[0], assignments,
    }
    const errors: string[] = [], reads: string[] = [], writes: string[] = []
    const metrics: unknown[] = []
    page.on('pageerror', error => errors.push(error.message))
    await context.routeWebSocket('**/aiyoloapi/**', () => {})
    await context.route('**/aiyoloapi/**', async route => {
      const request = route.request(), url = new URL(request.url()), path = unscopedPath(url.pathname)
      if (request.method() !== 'GET') { writes.push(`${request.method()} ${path}`); await route.abort(); return }
      const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
      if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: fixtureUser() })
      if (path.endsWith('/auth/me')) return reply(fixtureUser())
      if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [fixtureProject] })
      if (path === '/aiyoloapi') return reply(fixtureProject)
      if (path.endsWith('/model-assignments')) return reply({ assignments })
      if (path.endsWith('/models')) return reply({ models: [model] })
      if (path.endsWith(`/models/${modelId}/parameters`)) {
        reads.push(url.search)
        const platform = url.searchParams.get('platform')
        return reply({
          schemaVersion: 2, modelId, modelVersion, platform, revision: platform === 'server' ? 7 : 11, source: 'platform',
          detection: { confidenceThreshold: platform === 'server' ? .35 : .4, iouThreshold: .45, maxDetections: 100 },
          alertRules: ['MAJOR', 'CRITICAL', 'MINOR'].map((severity, index) => ({
            rawLabel: index === 0 ? 'helmet_without_spaces_'.repeat(4) : `class_${index}`,
            displayName: index === 0 ? '作业人员未正确佩戴安全帽长名称测试'.repeat(3) : index === 1 ? '危险区域入侵' : '作业人员',
            eventCode: index === 0 ? 'HELMET_INSPECTION_EVENT_WITHOUT_SPACES_FOR_LAYOUT_VALIDATION' : `EVENT_${index}`,
            operator: 'PRESENCE', enabled: index !== 1, severity,
            image: { minimumConfidence: .55, cooldownMs: 86400000 },
            camera: { minimumConfidence: .65, minimumConsecutiveFrames: 3, minimumDwellTimeMs: 1200, cooldownMs: 5000 },
          })),
          audit: [{ action: 'publish', revision: 7, actor: 'platform-administrator-with-a-long-name'.repeat(2), at: '2026-11-17T08:00:00Z' }],
        })
      }
      return reply({}, 404)
    })
    await page.setViewportSize({ width, height: 960 })
    await page.goto(adminPath('/project-models'))
    for (const target of ['pc', 'mobile']) {
      const platform = target === 'pc' ? 'server' : 'android'
      await page.locator(`#project-model-tab-${target}`).click()
      await page.getByRole('button', { name: '查看平台参数', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '查看平台参数', exact: true })
      await expect(dialog.locator('.parameter-profile-meta')).toContainText(target === 'pc' ? 'r7' : 'r11')
      await expect(dialog.getByRole('tab')).toHaveCount(1)
      await expect(dialog.getByRole('tab')).toContainText(target === 'pc' ? '服务端参数' : 'Android 参数')
      await expect(dialog.locator('.parameter-identity h3')).toHaveText(modelName)
      await expect(dialog.locator('.parameter-detection-values')).toContainText(target === 'pc' ? '0.35' : '0.4')
      await expect(dialog.locator('.parameter-readonly')).toContainText('共 3 类 · 已启用 2 类')
      await expect(dialog.locator('input[type="number"],[role="switch"],form')).toHaveCount(0)
      for (const action of ['保存草稿', '发布参数', '重置草稿']) {
        await expect(dialog.getByRole('button', { name: action, exact: true })).toHaveCount(0)
      }
      if ([1440, 390].includes(width) && target === 'mobile') {
        await dialog.locator('.parameter-identity').scrollIntoViewIfNeeded()
        await page.screenshot({ path: info.outputPath(`overview-${width}.png`), animations: 'disabled' })
      }
      const search = dialog.getByRole('textbox', { name: '搜索类别', exact: true })
      await search.fill('no-such-category')
      await expect(dialog.getByRole('status')).toContainText('未找到匹配的类别')
      await expect(dialog.getByRole('button', { name: '全部展开', exact: true })).toBeDisabled()
      await search.fill('helmet_inspection_event')
      await expect(dialog.locator('.parameter-readonly-rule')).toHaveCount(1)
      await search.fill('')
      await dialog.getByRole('button', { name: '全部展开', exact: true }).click()
      const rules = dialog.locator('.parameter-readonly-rule')
      await expect(rules).toHaveCount(3)
      await expect(rules.first().locator('.el-collapse-item__header')).toHaveAttribute('aria-expanded', 'true')
      await expect(rules.nth(1)).toContainText('此类别已关闭识别与告警')
      await expect(rules.first().locator('.parameter-event-code')).toContainText('HELMET_INSPECTION_EVENT_WITHOUT_SPACES_FOR_LAYOUT_VALIDATION')
      await expect(rules.first().locator('.parameter-rule-group').first()).toContainText('86400000 毫秒')
      await expect(rules.first().locator('.parameter-rule-group').last()).toContainText('1200 毫秒')
      await dialog.locator('.parameter-readonly-audit .el-collapse-item__header').click()
      const current = await layoutMetrics(dialog)
      metrics.push({ target, ...current })
      expect(current.overflow).toEqual([])
      expect(current.dialogOverflow).toBe(false);expect(current.bodyOverflow).toBe(false)
      expect(current.footerGap).toBeGreaterThanOrEqual(11)
      expect(current.groupGap).toBeGreaterThanOrEqual(11)
      expect(current.badgesSeparated).toBe(true)
      expect(current.groupsStacked).toBe(width <= 600)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      if ([1440, 390].includes(width) && target === 'mobile') {
        await rules.first().locator('.el-collapse-item__header').scrollIntoViewIfNeeded()
        await page.screenshot({ path: info.outputPath(`rules-${width}.png`), animations: 'disabled' })
      }
      await dialog.getByRole('button', { name: '全部收起', exact: true }).click()
      await expect(rules.first().locator('.el-collapse-item__header')).toHaveAttribute('aria-expanded', 'false')
      await rules.first().locator('.el-collapse-item__header').focus();await page.keyboard.press('Enter')
      await expect(rules.first().locator('.el-collapse-item__header')).toHaveAttribute('aria-expanded', 'true')
      await dialog.getByRole('button', { name: '重新读取档案', exact: true }).click()
      await expect(dialog.locator('.parameter-profile-meta')).toContainText(target === 'pc' ? 'r7' : 'r11')
      expect(reads.filter(query => query === `?platform=${platform}&version=${modelVersion}`)).toHaveLength(2)
      await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0)
    }
    expect(reads).toHaveLength(4);expect(writes).toEqual([]);expect(errors).toEqual([])
    console.log(JSON.stringify({ width, browser: context.browser()!.version(), metrics, reads, writes, errors }))
  })
}
