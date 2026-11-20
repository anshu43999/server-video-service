import { expect, test, type BrowserContext, type Locator } from '@playwright/test'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'
import { adminPath } from './helpers/navigation'

const modelId = 'platform-editor-06b4dd2f10544673ab723226f91c34a7', modelVersion = '2.0.0'
const modelName = '安全帽巡检 / HelmetInspectionModelWithoutSpaces'.repeat(2)
function profile(platform: string) {
  const revision = platform === 'server' ? 11 : 7
  return {
    schemaVersion: 2, modelId, modelVersion, platform, revision, publishedRevision: revision, hasUnpublishedChanges: false, source: 'custom',
    detection: { confidenceThreshold: .35, iouThreshold: .45, maxDetections: 100 },
    alertRules: ['MAJOR', 'CRITICAL', 'MINOR'].map((severity, index) => ({
      rawLabel: index === 0 ? 'helmet_without_spaces_'.repeat(3) : `class_${index}`,
      displayName: index === 0 ? '未佩戴安全帽长名称布局测试'.repeat(3) : index === 1 ? '危险区域入侵' : '作业人员',
      eventCode: index === 0 ? 'HELMET_INSPECTION_EVENT_WITHOUT_SPACES_FOR_LAYOUT_VALIDATION' : `EVENT_${index}`,
      operator: 'PRESENCE', enabled: index !== 1, severity,
      image: { minimumConfidence: .55, cooldownMs: 86400000 },
      camera: { minimumConfidence: .55, minimumConsecutiveFrames: 3, minimumDwellTimeMs: 1200, cooldownMs: 5000 },
    })),
    audit: [{ action: 'UPDATED', revision, actor: 'platform-administrator-with-a-long-name'.repeat(2), at: '2026-11-17T08:00:00Z' }],
  }
}
type Write = { method: string; path: string; query: string; body: any }
async function service(context: BrowserContext, conflict = false) {
  const profiles = { android: profile('android'), server: profile('server') }
  const writes: Write[] = [], reads: string[] = []
  await context.routeWebSocket('**/aiyoloapi/**', () => {})
  await context.route('**/healthz', route => route.fulfill({ json: { status: 'ok' } }))
  await context.route('**/aiyoloapi/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
    if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: fixtureUser() })
    if (path.endsWith('/auth/me')) return reply(fixtureUser())
    if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [fixtureProject] })
    if (path === '/aiyoloapi/models' && method === 'GET') return reply({ models: [{
      modelId, version: modelVersion, name: modelName, status: 'PUBLISHED', supportedTargets: ['pc', 'mobile'],
      serverReady: true, androidReady: true, serverBindable: true, signatureStatus: 'verified', labels: ['helmet'], artifacts: [],
    }] })
    const platform = url.searchParams.get('platform') === 'server' ? 'server' : 'android'
    const current = profiles[platform]
    if (method !== 'GET') writes.push({ method, path, query: url.search, body: request.postData() ? request.postDataJSON() : null })
    if (path === `/aiyoloapi/models/${modelId}/parameters`) {
      if (method === 'GET') { reads.push(url.search); return reply(current) }
      if (method === 'PUT') {
        if (conflict) return reply({ detail: { code: 'revision_conflict', message: '档案修订冲突，请重新读取' } }, 409)
        const body = request.postDataJSON()
        profiles[platform] = { ...current, detection: body.detection, alertRules: body.alertRules, revision: current.revision + 1, hasUnpublishedChanges: true, source: 'custom' }
        return reply(profiles[platform])
      }
      if (method === 'DELETE') {
        profiles[platform] = { ...profile(platform), revision: current.revision + 1, publishedRevision: current.publishedRevision, hasUnpublishedChanges: true }
        return reply(profiles[platform])
      }
    }
    if (path === `/aiyoloapi/platform/models/${modelId}/parameters/publish` && method === 'POST') {
      current.publishedRevision = current.revision;current.hasUnpublishedChanges = false
      return reply({ ...current, source: 'platform' })
    }
    return reply({}, 404)
  })
  return { writes, reads }
}

async function layoutMetrics(dialog: Locator) {
  return dialog.evaluate(element => {
    const selectors = '.parameter-content,.parameter-editor-meta,.parameter-editor-state,.parameter-editor-basics,.parameter-editor-toolbar,.parameter-editor-rule,.parameter-editor-rule-title,.parameter-editor-groups,.parameter-editor-group,.parameter-editor-audit,.parameter-editor-actions,.parameter-editor-button-groups'
    const overflow = [...element.querySelectorAll<HTMLElement>(selectors)]
      .filter(node => node.clientWidth > 0 && node.scrollWidth > node.clientWidth + 1).map(node => node.className)
    const name = element.querySelector('.parameter-editor-rule-name')!.getBoundingClientRect()
    const badges = element.querySelector('.parameter-editor-rule-badges')!.getBoundingClientRect()
    const groups = element.querySelectorAll('.parameter-editor-rule .parameter-editor-group')
    const first = groups[0]!.getBoundingClientRect(), second = groups[1]!.getBoundingClientRect()
    const footer = element.querySelector('.parameter-editor-actions')!
    const note = footer.querySelector('.parameter-editor-operation-note')!.getBoundingClientRect()
    const buttons = footer.querySelector('.parameter-editor-button-groups')!.getBoundingClientRect()
    const context = document.createElement('canvas').getContext('2d')!
    const clippedNumbers = [...element.querySelectorAll<HTMLInputElement>('.ui-number-input input')].filter(input => {
      if (!input.clientWidth) return false
      const style = getComputedStyle(input)
      context.font = style.font || `${style.fontSize} ${style.fontFamily}`
      return context.measureText(input.value).width > input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) + 1
    }).map(input => input.value)
    return {
      overflow, clippedNumbers,
      badgesSeparated: badges.top >= name.bottom - 1 || badges.left >= name.right - 1,
      groupsStacked: second.top >= first.bottom,
      groupGap: second.top >= first.bottom ? second.top - first.bottom : second.left - first.right,
      footerGap: buttons.top - note.bottom,
      bodyOverflow: element.querySelector('.el-dialog__body')!.scrollWidth > element.querySelector('.el-dialog__body')!.clientWidth + 1,
    }
  })
}

for (const width of [1440, 768, 390, 320]) {
  test(`platform draft editing and confirmed publication remain clear at ${width}px`, async ({ context, page }, info) => {
    const { writes, reads } = await service(context)
    const errors: string[] = [], metrics: unknown[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.setViewportSize({ width, height: 960 })
    await page.goto(adminPath('/models'))
    await page.getByRole('button', { name: '参数档案', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '模型参数档案', exact: true })
    for (const platform of ['android', 'server']) {
      const initialRevision = platform === 'server' ? 11 : 7
      if (platform === 'server') await dialog.getByRole('tab', { name: '服务端参数', exact: true }).click()
      await expect(dialog.locator('.parameter-editor-meta')).toContainText(`草稿修订r${initialRevision}`)
      await expect(dialog.locator('.parameter-editor-meta')).toContainText(`已发布修订r${initialRevision}`)
      await expect(dialog.locator('.parameter-editor-state')).toContainText('与发布版一致')
      const publish = dialog.getByRole('button', { name: '发布参数', exact: true })
      await expect(publish).toBeDisabled()
      const search = dialog.getByRole('textbox', { name: '搜索类别', exact: true })
      await search.fill('absent-category')
      await expect(dialog.locator('.parameter-editor-empty')).toContainText('未找到匹配的类别')
      await search.fill('helmet_inspection_event')
      await expect(dialog.locator('.parameter-editor-rule')).toHaveCount(1)
      await search.fill('')
      await expect(dialog.locator('.parameter-editor-state')).toContainText('与发布版一致')
      if ([1440, 390].includes(width) && platform === 'android') {
        await dialog.locator('.parameter-identity').scrollIntoViewIfNeeded()
        await page.screenshot({ path: info.outputPath(`editor-overview-${width}.png`), animations: 'disabled' })
      }
      await dialog.getByLabel('识别置信度', { exact: true }).fill('0.4')
      await expect(dialog.locator('.parameter-editor-state')).toContainText('有未保存编辑')
      await expect(publish).toBeDisabled()
      const expand = dialog.getByRole('button', { name: '全部展开', exact: true })
      if (await expand.count()) await expand.click()
      const first = dialog.locator('.parameter-editor-rule').first()
      await first.getByLabel('业务名称', { exact: true }).fill('修改后的安全帽告警规则')
      await first.getByLabel('事件编码', { exact: true }).fill('HELMET_LAYOUT_UPDATED')
      await first.locator('.el-select__wrapper').click()
      await page.getByRole('option', { name: '严重', exact: true }).last().click()
      await first.getByLabel('最少连续帧', { exact: true }).fill('6')
      await first.getByLabel('最少停留时间（毫秒）', { exact: true }).fill('2400')
      await first.locator('.el-switch').click()
      await expect(first.locator('.parameter-editor-rule-badges')).toContainText('识别与告警已关闭')
      await first.locator('.el-switch').click()
      await expect(first.locator('.parameter-editor-rule-badges')).toContainText('严重告警')
      await dialog.locator('.parameter-editor-audit .el-collapse-item__header').click()
      const current = await layoutMetrics(dialog);metrics.push({ platform, ...current })
      expect(current.overflow).toEqual([]);expect(current.clippedNumbers).toEqual([])
      expect(current.bodyOverflow).toBe(false);expect(current.badgesSeparated).toBe(true)
      expect(current.groupsStacked).toBe(width <= 600)
      expect(current.groupGap).toBeGreaterThanOrEqual(11);expect(current.footerGap).toBeGreaterThanOrEqual(13)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      if ([1440, 390].includes(width) && platform === 'android') {
        await first.locator('.el-collapse-item__header').scrollIntoViewIfNeeded()
        await page.screenshot({ path: info.outputPath(`editor-groups-${width}.png`), animations: 'disabled' })
      }
      await dialog.getByRole('button', { name: '保存草稿', exact: true }).click()
      await expect(dialog.locator('.parameter-editor-state')).toContainText('草稿待发布')
      await expect(dialog.locator('.parameter-editor-meta')).toContainText(`草稿修订r${initialRevision + 1}`)
      await expect(dialog.locator('.parameter-editor-meta')).toContainText(`已发布修订r${initialRevision}`)
      const saved = writes.filter(write => write.method === 'PUT' && write.query.includes(`platform=${platform}`))
      expect(saved).toHaveLength(1)
      expect(saved[0]!.query).toBe(`?platform=${platform}&version=${modelVersion}`)
      expect(saved[0]!.body).toMatchObject({ schemaVersion: 2, expectedRevision: initialRevision, detection: { confidenceThreshold: .4 }, alertRules: [{ displayName: '修改后的安全帽告警规则', eventCode: 'HELMET_LAYOUT_UPDATED', enabled: true, severity: 'CRITICAL', camera: { minimumConsecutiveFrames: 6, minimumDwellTimeMs: 2400 } }, {}, {}] })
      expect(writes.filter(write => write.method === 'POST' && write.query.includes(`platform=${platform}`))).toHaveLength(0)
      if ([1440, 390].includes(width) && platform === 'android') {
        await dialog.locator('.parameter-editor-actions').scrollIntoViewIfNeeded()
        await page.screenshot({ path: info.outputPath(`editor-actions-${width}.png`), animations: 'disabled' })
      }
      await publish.click()
      let confirmation = page.getByRole('alertdialog', { name: '发布平台参数', exact: true })
      await confirmation.getByRole('button', { name: '取消', exact: true }).click()
      await expect(confirmation).toHaveCount(0)
      expect(writes.filter(write => write.method === 'POST' && write.query.includes(`platform=${platform}`))).toHaveLength(0)
      await publish.click()
      confirmation = page.getByRole('alertdialog', { name: '发布平台参数', exact: true })
      await confirmation.getByRole('button', { name: '确认发布', exact: true }).click()
      await expect(confirmation).toHaveCount(0)
      await expect(dialog.locator('.parameter-editor-state')).toContainText('与发布版一致')
      await expect(dialog.locator('.parameter-editor-meta')).toContainText(`已发布修订r${initialRevision + 1}`)
      expect(writes.filter(write => write.method === 'POST' && write.query.includes(`platform=${platform}`))[0]).toMatchObject({
        path: `/aiyoloapi/platform/models/${modelId}/parameters/publish`, query: `?platform=${platform}&version=${modelVersion}`,
        body: { expectedRevision: initialRevision + 1, expectedPublishedRevision: initialRevision },
      })
      await dialog.getByRole('button', { name: '重置草稿', exact: true }).click()
      confirmation = page.getByRole('alertdialog', { name: '重置参数草稿', exact: true })
      await confirmation.getByRole('button', { name: '取消恢复', exact: true }).click()
      expect(writes.filter(write => write.method === 'DELETE' && write.query.includes(`platform=${platform}`))).toHaveLength(0)
      await dialog.getByRole('button', { name: '重置草稿', exact: true }).click()
      await page.getByRole('alertdialog', { name: '重置参数草稿', exact: true }).getByRole('button', { name: '确认恢复', exact: true }).click()
      await expect(dialog.locator('.parameter-editor-meta')).toContainText(`草稿修订r${initialRevision + 2}`)
      await expect(dialog.locator('.parameter-editor-meta')).toContainText(`已发布修订r${initialRevision + 1}`)
      await expect(dialog.locator('.parameter-editor-state')).toContainText('草稿待发布')
      expect(writes.filter(write => write.method === 'DELETE' && write.query.includes(`platform=${platform}`))).toEqual([expect.objectContaining({
        query: `?platform=${platform}&version=${modelVersion}&expectedRevision=${initialRevision + 1}`,
      })])
      await dialog.getByRole('button', { name: '重新读取档案', exact: true }).click()
      await expect(dialog.locator('.parameter-editor-meta')).toContainText(`草稿修订r${initialRevision + 2}`)
      expect(reads.filter(query => query === `?platform=${platform}&version=${modelVersion}`)).toHaveLength(2)
    }
    expect(writes.map(write => write.method)).toEqual(['PUT', 'POST', 'DELETE', 'PUT', 'POST', 'DELETE'])
    expect(errors).toEqual([])
    console.log(JSON.stringify({ width, browser: context.browser()!.version(), metrics, reads, writeMethods: writes.map(write => write.method), errors }))
  })
}

test('platform conflict preserves edits and blocks further writes until a read', async ({ context, page }) => {
  const { writes, reads } = await service(context, true)
  await page.goto(adminPath('/models'))
  await page.getByRole('button', { name: '参数档案', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '模型参数档案', exact: true })
  await dialog.getByLabel('识别置信度', { exact: true }).fill('0.4')
  await dialog.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('档案修订冲突')
  await expect(dialog.locator('.parameter-editor-state')).toContainText('需要重新核验')
  await expect(dialog.getByLabel('识别置信度', { exact: true })).toHaveValue('0.4')
  for (const name of ['保存草稿', '发布参数', '重置草稿']) await expect(dialog.getByRole('button', { name, exact: true })).toBeDisabled()
  expect(writes).toHaveLength(1)
  await dialog.getByRole('button', { name: '重新读取档案', exact: true }).click()
  await expect(dialog.getByLabel('识别置信度', { exact: true })).toHaveValue('0.35')
  await expect(dialog.getByRole('button', { name: '保存草稿', exact: true })).toBeEnabled()
  expect(reads).toHaveLength(2);expect(writes).toHaveLength(1)
})
