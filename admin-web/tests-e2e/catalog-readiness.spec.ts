import { expect, test, type Locator } from '@playwright/test'
import { adminPath } from './helpers/navigation'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'
import type { ParameterProfile, Platform } from '../src/features/models/types'

function profile(platform: Platform): ParameterProfile {
  return { modelId: 'phone', modelVersion: '1.0.0', platform, schemaVersion: 2, revision: 0,
    source: 'default', publishedRevision: null, hasUnpublishedChanges: true,
    detection: { confidenceThreshold: .35, iouThreshold: .45, maxDetections: 100 }, alertRules: [] }
}

async function layout(card: Locator) {
  return card.evaluate(element => {
    const rows = [...element.querySelectorAll<HTMLElement>('.catalog-readiness-row')]
    return {
      pageOverflow: document.documentElement.scrollWidth > innerWidth,
      overflow: [...element.querySelectorAll<HTMLElement>('.catalog-readiness,.catalog-readiness-row')]
        .filter(el => el.scrollWidth > el.clientWidth + 1).map(el => el.className),
      buttonGaps: rows.map(row => {
        const button = row.querySelector('button')!.getBoundingClientRect()
        const content = row.querySelector('.catalog-readiness-main')!.getBoundingClientRect()
        return Math.max(button.left - content.right, button.top - content.bottom)
      }),
      hintOverlaps: rows.filter(row => {
        const hint = row.querySelector('p')?.getBoundingClientRect()
        const button = row.querySelector('button')!.getBoundingClientRect()
        return hint && hint.left < button.right && hint.right > button.left
          && hint.top < button.bottom && hint.bottom > button.top
      }).length,
    }
  })
}

for (const width of [1440, 390, 320]) {
  for (const platform of ['server', 'android'] as const) {
    test(`catalog explains and resolves ${platform} publication at ${width}px`, async ({ page, context }, info) => {
      const profiles = { server: profile('server'), android: profile('android') }
      const writes: { method: string; platform: string; version: string; body: unknown }[] = []
      const errors: string[] = [], unexpected: string[] = [], metrics: unknown[] = []
      page.on('pageerror', error => errors.push(error.message))
      await context.routeWebSocket('**/aiyoloapi/**', () => {})
      await context.route('**/aiyoloapi/**', async route => {
        const request = route.request(), url = new URL(request.url()), path = url.pathname
        const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
        if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: fixtureUser() })
        if (path.endsWith('/auth/me')) return reply(fixtureUser())
        if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [fixtureProject] })
        if (path.endsWith('/models') && request.method() === 'GET') return reply({ models: [{
          modelId: 'phone', name: '手机检测 phone', version: '1.0.0', status: 'PUBLISHED', releaseEligible: true,
          supportedTargets: ['pc', 'mobile'], serverReady: true, androidReady: true, signatureStatus: 'signed',
          targetReleaseEligible: { pc: true, mobile: true }, labels: [],
          parameterPublication: Object.fromEntries(Object.entries(profiles).map(([end, p]) => [end, {
            state: p.publishedRevision == null ? 'unpublished' : 'published',
            publishedRevision: p.publishedRevision, hasUnpublishedChanges: p.hasUnpublishedChanges,
          }])),
        }] })
        if (/\/models\/phone\/parameters(?:\/publish)?$/.test(path)) {
          const end = url.searchParams.get('platform') as Platform
          expect(['server', 'android']).toContain(end)
          expect(url.searchParams.get('version')).toBe('1.0.0')
          if (request.method() === 'GET') return reply(profiles[end])
          const body = request.postDataJSON()
          writes.push({ method: request.method(), platform: end, version: url.searchParams.get('version')!, body })
          if (request.method() === 'PUT' && body.expectedRevision === profiles[end].revision) {
            profiles[end] = { ...profiles[end], detection: body.detection, alertRules: body.alertRules,
              revision: profiles[end].revision + 1, source: 'custom', hasUnpublishedChanges: true }
            return reply(profiles[end])
          }
          if (request.method() === 'POST' && path.endsWith('/publish')) {
            expect(body).toEqual({ expectedRevision: 1, expectedPublishedRevision: null })
            profiles[end] = { ...profiles[end], publishedRevision: profiles[end].revision, source: 'platform', hasUnpublishedChanges: false }
            return reply(profiles[end])
          }
          return reply({ detail: 'unexpected publication fixture' }, 409)
        }
        unexpected.push(`${request.method()} ${path}`)
        return route.abort()
      })
      await page.setViewportSize({ width, height: 960 })
      await page.goto(adminPath('/models'))
      const card = page.locator('.model-card')
      await expect(card.locator('.catalog-readiness-row')).toHaveCount(2)
      await expect(card).toContainText('尚未出现在项目“添加模型”中')
      await expect(card.getByText('待发布参数', { exact: true })).toHaveCount(2)
      let check = await layout(card)
      expect(check.pageOverflow).toBe(false); expect(check.overflow).toEqual([])
      expect(check.buttonGaps.every(gap => gap >= 6)).toBe(true)
      expect(check.hintOverlaps).toBe(0)
      metrics.push({ state: 'unpublished', ...check })
      await card.locator('.catalog-readiness').evaluate(element => element.scrollIntoView({ block: 'center' }))
      await card.locator('.catalog-readiness').screenshot({ path: info.outputPath(`unpublished-${platform}-${width}.png`), animations: 'disabled' })
      expect(writes).toHaveLength(0)

      const name = platform === 'server' ? '服务端参数' : 'Android 参数'
      await card.getByRole('button', { name: `去发布${name}`, exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '模型参数档案', exact: true })
      await expect(dialog).toBeVisible()
      await expect(dialog.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true')
      await expect(dialog.locator('.parameter-editor-meta')).toContainText('尚未发布')
      expect(writes).toHaveLength(0)
      await dialog.getByRole('spinbutton', { name: /^识别置信度(?:\s|$)/ }).fill('.4')
      await dialog.getByRole('button', { name: '保存草稿', exact: true }).click()
      await expect(dialog).toContainText('草稿已保存')
      await dialog.getByRole('button', { name: '发布参数', exact: true }).click()
      const confirmation = page.getByRole('alertdialog', { name: '发布平台参数', exact: true })
      await confirmation.getByRole('button', { name: '取消', exact: true }).click()
      expect(writes).toHaveLength(1)
      await dialog.getByRole('button', { name: '发布参数', exact: true }).click()
      await confirmation.getByRole('button', { name: '确认发布', exact: true }).click()
      await expect(dialog).toContainText('参数已发布')
      await dialog.getByRole('button', { name: '关闭此对话框', exact: true }).click()
      await expect(dialog).toHaveCount(0)
      const updated = card.locator('.catalog-readiness-row').filter({ hasText: platform === 'server' ? 'PC 端' : '移动端' })
      await expect(updated).toContainText('项目可添加')
      await expect(updated).toContainText('已发布 r1')
      await expect(card.getByText('待发布参数', { exact: true })).toHaveCount(1)
      expect(writes.map(({ method, platform: end, version }) => [method, end, version])).toEqual([
        ['PUT', platform, '1.0.0'], ['POST', platform, '1.0.0'],
      ])
      check = await layout(card)
      expect(check.pageOverflow).toBe(false); expect(check.overflow).toEqual([])
      expect(check.buttonGaps.every(gap => gap >= 6)).toBe(true)
      expect(check.hintOverlaps).toBe(0)
      metrics.push({ state: 'published', ...check })
      await card.locator('.catalog-readiness').evaluate(element => element.scrollIntoView({ block: 'center' }))
      await card.locator('.catalog-readiness').screenshot({ path: info.outputPath(`published-${platform}-${width}.png`), animations: 'disabled' })
      expect(errors).toEqual([]); expect(unexpected).toEqual([])
      console.log(JSON.stringify({ width, platform, metrics, writes: writes.length, errors, unexpected }))
    })
  }
}

for (const [width, height] of [[1440, 900], [1366, 768], [1280, 720], [390, 844], [320, 740]]) {
  test(`compact catalog keeps two cards and accessible details at ${width}px`, async ({ page, context }, info) => {
    const errors: string[] = [], unexpected: string[] = [], writes: string[] = []
    const assets = [
      { modelId: 'uploaded-98a1f0c8541549e482289c8f9c9246c8', name: '手机检测 phone', version: '1.0.0' },
      { modelId: 'uploaded-06b4dd2f10544673ab723226f91c34a7', name: '安全帽与现场人员检测 · 多目标巡检模型', version: '2.0.0' },
    ].map((asset, index) => ({
      ...asset, status: 'PUBLISHED', releaseEligible: true, supportedTargets: ['pc', 'mobile'],
      serverReady: true, androidReady: true, signatureStatus: 'signed', serverBindable: true,
      targetReleaseEligible: { pc: true, mobile: true }, scenario: '现场巡检',
      labels: Array.from({ length: 80 }, (_, label) => `inspection_class_${label}`),
      parameterPublication: {
        server: { state: 'unpublished', publishedRevision: null, hasUnpublishedChanges: true },
        android: { state: index ? 'published' : 'unpublished', publishedRevision: index ? 4 : null, hasUnpublishedChanges: !index },
      },
    }))
    page.on('pageerror', error => errors.push(error.message))
    await context.routeWebSocket('**/aiyoloapi/**', () => {})
    await context.route('**/aiyoloapi/**', route => {
      const request = route.request(), path = new URL(request.url()).pathname
      const reply = (json: unknown) => route.fulfill({ json })
      if (request.method() !== 'GET') { writes.push(`${request.method()} ${path}`); return route.abort() }
      if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: fixtureUser() })
      if (path.endsWith('/auth/me')) return reply(fixtureUser())
      if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [fixtureProject] })
      if (path === '/aiyoloapi/models') return reply({ models: assets })
      if (path.endsWith('/removal-impact')) return reply({
        safeToRemove: true, expectedRevision: 1, knownDevices: 0, unknownDeviceCount: 0,
        dependentCounts: { assignments: 0, scenes: 0, plans: 0, streams: 0, activeSlots: 0 },
      })
      if (path.endsWith('/versions/1.0.0')) return reply(assets[0])
      unexpected.push(`${request.method()} ${path}`); return route.abort()
    })
    await page.setViewportSize({ width, height })
    await page.goto(adminPath('/models'))
    const cards = page.locator('.catalog-grid .model-card')
    await expect(cards).toHaveCount(2)
    const metrics = await cards.evaluateAll(elements => elements.map(element => {
      const rect = element.getBoundingClientRect()
      return { top: rect.top, bottom: rect.bottom, height: rect.height, left: rect.left, right: rect.right }
    }))
    if (width >= 1280) {
      expect(metrics[0]!.top).toBe(metrics[1]!.top)
      for (const card of metrics) {
        expect(card.top).toBeGreaterThanOrEqual(0)
        expect(card.bottom).toBeLessThanOrEqual(height)
        expect(card.height).toBeLessThanOrEqual(440)
      }
    }
    for (const card of await cards.all()) {
      const geometry = await layout(card)
      expect(geometry.pageOverflow).toBe(false); expect(geometry.overflow).toEqual([])
      expect(geometry.hintOverlaps).toBe(0)
      await expect(card.locator('.catalog-technical')).not.toHaveAttribute('open', '')
      for (const name of ['版本详情', '参数档案', '按端发布', '卸载']) {
        await expect(card.getByRole('button', { name, exact: true })).toBeVisible()
      }
    }
    await page.screenshot({ path: info.outputPath(`compact-${width}.png`), fullPage: true })
    const first = cards.first(), technical = first.locator('.catalog-technical')
    await technical.locator('summary').click()
    await expect(technical).toHaveAttribute('open', '')
    await expect(technical).toContainText(assets[0]!.modelId)
    await expect(technical).toContainText('inspection_class_79')
    await expect(first.getByRole('button', { name: '验证 PC 运行时', exact: true })).toBeVisible()
    await expect(first.getByRole('button', { name: '设为新流默认', exact: true })).toBeEnabled()
    expect(await technical.evaluate(el => el.scrollWidth > el.clientWidth + 1)).toBe(false)
    await technical.locator('summary').click()
    await first.getByRole('button', { name: '按端发布', exact: true }).click()
    const publish = page.getByRole('dialog', { name: '按目标端发布模型', exact: true })
    await expect(publish).toBeVisible()
    await publish.getByRole('button', { name: '取消', exact: true }).click()
    await first.getByRole('button', { name: '版本详情', exact: true }).click()
    const detail = page.getByRole('dialog', { name: '模型版本详情', exact: true })
    await expect(detail).toContainText(assets[0]!.modelId)
    await detail.getByRole('button', { name: '关闭此对话框', exact: true }).click()
    await first.getByRole('button', { name: '卸载', exact: true }).click()
    const removal = page.getByRole('dialog', { name: '卸载模型版本：影响确认', exact: true })
    await expect(removal).toBeVisible()
    await expect(removal.getByRole('button', { name: '确认卸载', exact: true })).toBeDisabled()
    await removal.getByRole('button', { name: '取消', exact: true }).click()
    expect(writes).toEqual([]); expect(errors).toEqual([]); expect(unexpected).toEqual([])
    console.log(JSON.stringify({ compact: true, width, height, cards: metrics, writes, errors, unexpected }))
  })
}
