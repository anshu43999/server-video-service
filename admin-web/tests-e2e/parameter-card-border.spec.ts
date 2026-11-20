import { expect, test, type Locator } from '@playwright/test'
import { fixtureProject, fixtureUser, unscopedPath } from './helpers/project-fixture'
import { adminPath } from './helpers/navigation'

async function borders(cards: Locator) {
  return cards.evaluateAll(elements => elements.map(element => {
    const card = element.getBoundingClientRect(), style = getComputedStyle(element)
    const item = element.querySelector('.el-collapse-item')!
    const header = element.querySelector('.el-collapse-item__header')!
    return {
      bottomWidth: parseFloat(style.borderBottomWidth), bottomStyle: style.borderBottomStyle,
      bottomColor: style.borderBottomColor, topColor: style.borderTopColor,
      itemMargin: getComputedStyle(item).marginBottom,
      contentClearance: card.bottom - item.getBoundingClientRect().bottom,
      headerClearance: card.bottom - header.getBoundingClientRect().bottom,
      overflow: element.scrollWidth > element.clientWidth + 1,
    }
  }))
}

for (const mode of ['editor', 'readonly'] as const) for (const width of [1440, 390]) {
  test(`${mode} category borders stay visible after toggling at ${width}px`, async ({ context, page }, info) => {
    const modelId = 'border-helmet', modelVersion = '2.0.0', writes: string[] = [], errors: string[] = []
    const assignment = { projectModelId: 'border-assignment', projectId: fixtureProject.projectId, modelId, modelVersion, target: 'pc', parameterPlatform: 'server', parameterRevision: 7, parameterPublished: true, enabled: true, revision: 1 }
    const model = { modelId, version: modelVersion, name: '安全帽巡检', status: 'PUBLISHED', supportedTargets: ['pc', 'mobile'], serverReady: true, androidReady: true, serverBindable: true, androidBindable: true, signatureStatus: 'verified', artifacts: [], labels: ['head', 'helmet', 'person'], assignment, assignments: [assignment] }
    page.on('pageerror', error => errors.push(error.message))
    await context.routeWebSocket('**/aiyoloapi/**', () => {})
    await context.route('**/healthz', route => route.fulfill({ json: { status: 'ok' } }))
    await context.route('**/aiyoloapi/**', route => {
      const request = route.request(), url = new URL(request.url()), path = unscopedPath(url.pathname)
      const reply = (json: unknown, status = 200) => route.fulfill({ json, status })
      if (request.method() !== 'GET') { writes.push(`${request.method()} ${path}`); return route.abort() }
      if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: fixtureUser() })
      if (path.endsWith('/auth/me')) return reply(fixtureUser())
      if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [fixtureProject] })
      if (path === '/aiyoloapi') return reply(fixtureProject)
      if (path.endsWith('/model-assignments')) return reply({ assignments: [assignment] })
      if (path.endsWith('/models')) return reply({ models: [model] })
      if (path.endsWith(`/models/${modelId}/parameters`)) return reply({
        schemaVersion: 2, modelId, modelVersion, platform: url.searchParams.get('platform'), revision: 7,
        publishedRevision: 7, hasUnpublishedChanges: false, source: mode === 'editor' ? 'custom' : 'platform',
        detection: { confidenceThreshold: .35, iouThreshold: .45, maxDetections: 100 },
        alertRules: ['head', 'helmet', 'person'].map((rawLabel, index) => ({
          rawLabel, displayName: ['未佩戴安全帽', '安全帽', '人员'][index], eventCode: `EVENT_${index}`,
          operator: 'PRESENCE', enabled: index === 0, severity: 'MAJOR',
          image: { minimumConfidence: .55, cooldownMs: 5000 },
          camera: { minimumConfidence: .55, minimumConsecutiveFrames: 3, minimumDwellTimeMs: 1200, cooldownMs: 5000 },
        })), audit: [],
      })
      return reply({}, 404)
    })
    await page.setViewportSize({ width, height: 960 })
    await page.goto(adminPath(mode === 'editor' ? '/models' : '/project-models'))
    await page.getByRole('button', { name: mode === 'editor' ? '参数档案' : '查看平台参数', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: mode === 'editor' ? '模型参数档案' : '查看平台参数', exact: true })
    const cards = dialog.locator(mode === 'editor' ? '.parameter-editor-rule' : '.parameter-readonly-rule')
    await expect(cards).toHaveCount(3)
    const states: unknown[] = []
    for (const state of ['collapsed', 'expanded', 'collapsed-again']) {
      if (state !== 'collapsed') await dialog.getByRole('button', { name: state === 'expanded' ? '全部展开' : '全部收起', exact: true }).click()
      for (const card of await cards.all()) {
        await expect(card.locator('.el-collapse-item__header')).toHaveAttribute('aria-expanded', String(state === 'expanded'))
      }
      // Wait for the collapse transition to finish before measuring its box.
      await expect.poll(() => cards.locator('.el-collapse-transition-enter-active,.el-collapse-transition-leave-active').count()).toBe(0)
      const screenshot = { path: info.outputPath(`${mode}-${width}-${state}.png`), animations: 'disabled' as const }
      if (state === 'expanded') {
        // Tall cards are clipped by the dialog viewport; capture their bottom in view.
        await cards.first().locator(mode === 'editor' ? '.parameter-editor-group' : '.parameter-rule-group').last().scrollIntoViewIfNeeded()
        await cards.first().evaluate(card => {
          const viewport = card.closest('.el-dialog__body')!
          viewport.scrollTop += Math.max(0, card.getBoundingClientRect().bottom - viewport.getBoundingClientRect().bottom + 16)
        })
        await page.screenshot(screenshot)
      } else await cards.first().screenshot(screenshot)
      const measured = await borders(cards)
      console.log(JSON.stringify({ mode, width, state, measured }))
      states.push({ state, measured })
      for (const card of measured) {
        expect(card.bottomWidth).toBe(1);expect(card.bottomStyle).toBe('solid')
        expect(card.bottomColor).toBe(card.topColor)
        expect(card.bottomColor).not.toBe('rgba(0, 0, 0, 0)')
        // A child's background must not paint over the card's bottom border.
        expect(card.contentClearance).toBeGreaterThanOrEqual(.99)
        expect(card.headerClearance).toBeGreaterThanOrEqual(.99)
        expect(card.itemMargin).toBe('0px')
        expect(card.overflow).toBe(false)
      }
    }
    expect(writes).toEqual([]);expect(errors).toEqual([])
    console.log(JSON.stringify({ mode, width, browser: context.browser()!.version(), checkedStates: states.length, writes, errors }))
  })
}
