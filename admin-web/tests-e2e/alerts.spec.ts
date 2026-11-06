import { adminPath } from './helpers/navigation'
import { fixtureUser, fixtureProjects, fixtureProject, unscopedPath } from './helpers/project-fixture'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

type MockEvent = Record<string, any> & { eventId: string }

const evidenceImage = readFileSync(resolve(process.cwd(), 'tests-e2e/fixtures/evidence_helmet_violation.png'))

function eventFixtures(): MockEvent[] {
  return [
    {
      eventId: 'mobile:camera:PPE_NO_HELMET:critical', projectId: 'fixture-project', displayName: '未佩戴安全帽', ruleId: 'PPE_NO_HELMET', ruleVersion: 3,
      sourceId: 'camera:gate-01', origin: 'MOBILE_CAMERA', subjectKey: 'track:17', state: 'CONFIRMED',
      severity: 'MAJOR', notifySeverity: 'CRITICAL', confirmedAtUs: 1_750_000_123_456_789,
      evidence: { snapshotUri: '/aiyoloapi/alerts/evidence' }, model: { modelId: 'helmet-v4' },
      disposition: { status: 'OPEN', actor: null, actedAtUs: null },
    },
    {
      eventId: 'mobile:image:ZONE_ENTRY:missing', projectId: 'fixture-project', displayName: '人员进入危险区', ruleId: 'ZONE_ENTRY',
      sourceId: 'image:现场拍照', origin: 'MOBILE_IMAGE', subjectKey: 'person:4', state: 'CONFIRMED',
      severity: 'IMPORTANT', notifySeverity: 'IMPORTANT', confirmedAtUs: 1_750_000_120_000_321,
      evidence: {}, disposition: { status: 'OPEN', actor: null, actedAtUs: null },
    },
    {
      eventId: 'server:camera:OBSTRUCTION:normal', projectId: 'fixture-project', label: '通道遮挡', ruleId: 'OBSTRUCTION',
      sourceId: 'stream-west', origin: 'SERVER_STREAM', subjectKey: 'track:2', state: 'ENDED',
      severity: 'MINOR', notifySeverity: 'MINOR', confirmedAtUs: 1_750_000_100_000_111,
      evidence: {}, disposition: { status: 'ACKNOWLEDGED', actor: 'operator-a', actedAtUs: 1_750_000_110_000_000 },
    },
  ]
}

test('alert center labels source and combines source filtering with search', async ({ context, page }) => {
  const events = eventFixtures()
  events.push({
    eventId: 'legacy:unknown-origin', projectId: 'fixture-project', displayName: '来源缺失事件',
    sourceId: 'legacy-source', state: 'CONFIRMED', severity: 'MINOR', confirmedAtUs: 1_750_000_090_000_111,
    disposition: { status: 'OPEN' },
  })
  await mockIdentity(context)
  await mockAlerts(context, events)
  await installFakeSocket(page)
  await page.goto(adminPath('/alerts'))

  await expect(page.locator('.alert-event-row')).toHaveCount(4)
  await expect(page.locator('.alert-event-row').filter({ hasText: '通道遮挡' }).locator('.alert-origin-label')).toHaveText('视频流告警')
  await expect(page.locator('.alert-event-row').filter({ hasText: '未佩戴安全帽' }).locator('.alert-origin-label')).toHaveText('移动端相机')
  await expect(page.locator('.alert-event-row').first()).not.toContainText('stream-west')
  await expect(page.locator('.alert-event-row').first()).not.toContainText('track:')
  await expect(page.locator('.alert-event-row').filter({ hasText: '来源缺失事件' }).locator('.alert-origin-label')).toHaveText('来源未标记')

  await page.getByTestId('alert-origin-filter').click()
  await page.getByRole('option', { name: '视频流告警' }).click()
  await expect(page.locator('.alert-event-row')).toHaveCount(1)
  await expect(page.locator('.alert-event-row').first().locator('.alert-origin-label')).toHaveText('视频流告警')

  await page.getByTestId('alert-origin-filter').click()
  await page.getByRole('option', { name: '移动端本地告警' }).click()
  await expect(page.locator('.alert-event-row')).toHaveCount(2)
  await page.getByPlaceholder('搜索事件、规则、来源或 ID').fill('未佩戴安全帽')
  await expect(page.locator('.alert-event-row')).toHaveCount(1)
  await expect(page.locator('.alert-event-row').first().locator('.alert-origin-label')).toHaveText('移动端相机')
})

async function mockIdentity(context: BrowserContext) {
  await context.route('**/aiyoloapi/auth/status', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ setupRequired: false, authenticated: true, user: { username: 'visual-admin', role: 'admin' } }) }))
  await context.route('**/aiyoloapi/auth/me', (route) => route.fulfill({ json: fixtureUser() }))
  await context.route('**/aiyoloapi/auth/projects', route => route.fulfill({ json: fixtureProjects() }))
  await context.route('**/aiyoloapi/projects/fixture-project', route => route.fulfill({ json: fixtureProject }))
}

async function installFakeSocket(page: Page) {
  await page.addInitScript(() => {
    class FakeWebSocket {
      onopen: ((event: Event) => void) | null = null
      onmessage: ((event: MessageEvent) => void) | null = null
      onclose: ((event: CloseEvent) => void) | null = null
      onerror: ((event: Event) => void) | null = null
      constructor(_url: string) {
        ;(window as any).__publishAlert = (event: unknown) => this.onmessage?.(new MessageEvent('message', {
          data: JSON.stringify({ type: 'alert', event }),
        }))
        setTimeout(() => this.onopen?.(new Event('open')), 0)
      }
      close(code = 1000, reason = '') { this.onclose?.(new CloseEvent('close', { code, reason })) }
    }
    Object.defineProperty(window, 'WebSocket', { configurable: true, value: FakeWebSocket })
  })
}

async function mockAlerts(context: BrowserContext, events: MockEvent[], imageBytes = evidenceImage, imageType = 'image/png') {
  let dispositionPosts = 0
  let verificationPosts = 0
  await context.route('**/aiyoloapi/projects/fixture-project/alerts**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = unscopedPath(url.pathname)
    if (path === '/aiyoloapi/alerts') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ events }) })
      return
    }
    if (path.endsWith('/false-positives/export')) {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ format: 'aiyolo-false-positive-v1', entries: [] }) })
      return
    }
    const match = path.match(/^\/aiyoloapi\/alerts\/([^/]+)(?:\/(.*))?$/)
    const eventId = match ? decodeURIComponent(match[1]) : ''
    const suffix = match?.[2] ?? ''
    if (suffix === 'advice-generations/latest') return route.fulfill({ status: 404, json: { detail: { code: 'ADVICE_GENERATION_NOT_FOUND' } } })
    const event = events.find((item) => item.eventId === eventId)
    if (!event) { await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'event_not_found', message: 'alert event not found' } }) }); return }
    if (suffix === 'evidence') {
      if (eventId.endsWith(':critical')) await route.fulfill({ contentType: imageType, body: imageBytes })
      else await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'evidence_not_found', message: 'alert evidence not found' } }) })
      return
    }
    if (suffix === 'verification') {
      if (request.method() === 'POST') {
        verificationPosts += 1
        event.verification = { eventId, status: 'FAILED', verdict: null, failureKind: 'NOT_CONFIGURED', reason: '未配置可用的复核供应商或模型' }
      }
      await route.fulfill({ status: request.method() === 'POST' ? 202 : 200, contentType: 'application/json', body: JSON.stringify(event.verification ?? { eventId, status: 'UNREVIEWED', verdict: null, reason: '尚未执行多模态复核', source: 'NONE' }) })
      return
    }
    if (suffix === 'acknowledge' || suffix === 'false-positive') {
      dispositionPosts += 1
      event.disposition = { status: suffix === 'acknowledge' ? 'ACKNOWLEDGED' : 'FALSE_POSITIVE', actor: 'visual-admin', actedAtUs: 1_750_000_200_000_000 }
      if (suffix === 'false-positive') event.state = 'ENDED'
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(event) })
      return
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(event) })
  })
  return { dispositionPosts: () => dispositionPosts, verificationPosts: () => verificationPosts }
}

function collectErrors(page: Page) {
  const errors: string[] = []
  page.on('console', (message) => {
    const location = message.location().url
    if (message.type() === 'error' && !location.endsWith('/evidence')) errors.push(`${message.text()} ${location}`.trim())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

for (const width of [1440, 390]) {
  test(`open alert keeps scroll notes and evidence across polling and realtime at ${width}px`, async ({ context, page }) => {
    const events = eventFixtures().slice(0, 1)
    events[0]!.evidence.displayOverlay = { version: 1, capturedAtUs: 123, bakedIn: false,
      detections: [{ label: '安全帽', confidence: .91, box: { left: .25, top: .25, right: .75, bottom: .75 } }] }
    await mockIdentity(context)
    await mockAlerts(context, events)
    await installFakeSocket(page)
    await page.clock.install()
    await page.setViewportSize({ width, height: 700 })
    let listRequests = 0
    let evidenceRequests = 0
    page.on('request', request => {
      const path = new URL(request.url()).pathname
      if (path.endsWith('/alerts')) listRequests++
      if (path.endsWith('/evidence')) evidenceRequests++
    })
    await page.goto(adminPath('/alerts'))
    await page.locator('.alert-event-row').click()
    const detail = page.getByRole('dialog', { name: '未佩戴安全帽' })
    await expect(detail.locator('.evidence-box-label')).toHaveText('安全帽 91%')
    const note = detail.getByPlaceholder('记录判断依据或现场处理情况')
    await note.fill('现场核验中，请保留这段备注')
    const y = await detail.evaluate(element => {
      element.scrollTop = 360
      ;(window as any).__m29Image = element.querySelector('img')
      return element.scrollTop
    })
    expect(y).toBeGreaterThan(100)
    const initialEvidence = evidenceRequests
    for (let index = 0; index < 3; index++) {
      const previousRequests = listRequests
      events[0]!.lastSeenAtUs = 1_750_000_300_000_000 + index
      const response = page.waitForResponse(result => new URL(result.url()).pathname.endsWith('/alerts'))
      await page.clock.runFor(5100)
      await (await response).finished()
      await page.clock.runFor(50)
      await expect.poll(() => listRequests).toBeGreaterThan(previousRequests)
      await expect(note).toHaveValue('现场核验中，请保留这段备注')
      await expect.poll(() => detail.evaluate(element => element.scrollTop)).toBe(y)
      await expect(detail.locator('.evidence-box-label')).toHaveText('安全帽 91%')
      expect(await detail.evaluate(element => element.querySelector('img') === (window as any).__m29Image)).toBe(true)
      expect(evidenceRequests).toBe(initialEvidence)
    }
    await page.evaluate(event => (window as any).__publishAlert(event), {
      ...events[0], disposition: { status: 'ACKNOWLEDGED' },
    })
    await expect(detail.locator('.disposition-badge')).toHaveText('已确认')
    await expect(note).toHaveValue('现场核验中，请保留这段备注')
    await expect.poll(() => detail.evaluate(element => element.scrollTop)).toBe(y)
    expect(evidenceRequests).toBe(initialEvidence)
    await page.screenshot({ path: `../evidence/M29/M29-T20/stable-detail-${width}.png` })
    await detail.getByRole('button', { name: '关闭告警详情' }).click()
    await page.locator('.alert-event-row').click()
    await expect(detail.getByPlaceholder('记录判断依据或现场处理情况')).toHaveValue('')
  })
}

test('scene/model snapshots are readable and searchable in list and detail at desktop and narrow widths', async ({ context, page }) => {
  const events = eventFixtures()
  events[0]!.provenance = { kind: 'SCENE', scene: { sceneId: 's2', name: '场景02 · 联合巡检', revision: 3 },
    plan: { planId: 'p1', name: '联合相机方案' }, memberId: 'helmet-member',
    model: { modelId: 'uploaded-06abc', name: '安全帽检测', version: '2.0.0' } }
  await mockIdentity(context)
  await installFakeSocket(page)
  await mockAlerts(context, events)
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(adminPath('/alerts'))
    await page.getByPlaceholder('搜索事件、规则、来源或 ID').fill('安全帽检测')
    const row = page.locator('.alert-event-row')
    await expect(row).toHaveCount(1)
    await expect(row).toContainText('场景02 · 联合巡检')
    await expect(row).toContainText('安全帽检测 · 2.0.0')
    await page.getByPlaceholder('搜索事件、规则、来源或 ID').fill('场景02')
    await row.click()
    const facts = page.getByRole('region', { name: '事件事实', exact: true })
    await expect(facts).toContainText('场景02 · 联合巡检')
    await expect(facts).toContainText('联合相机方案')
    await expect(facts).toContainText('安全帽检测 · 2.0.0')
    await expect(page.locator('body')).toHaveJSProperty('scrollWidth', width)
    await page.screenshot({ path: `test-results/alert-provenance-${width}.png`, fullPage: true })
  }
})

for (const shape of ['landscape', 'portrait'] as const) {
  test(`new evidence overlay aligns in list and detail, resizes and skips baked ${shape}`, async ({ context, page }) => {
    const events = eventFixtures().slice(0, 1)
    events[0].evidence.displayOverlay = {
      version: 1, capturedAtUs: 123, bakedIn: false,
      detections: [{ label: '安全帽', confidence: .91, box: { left: .25, top: .25, right: .75, bottom: .75 } }],
    }
    // Rotate only the test fixture for a second intrinsic aspect ratio, not product evidence.
    const portrait = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="941" height="1672"><image href="data:image/png;base64,${evidenceImage.toString('base64')}" width="1672" height="941" transform="translate(941 0) rotate(90)" /></svg>`)
    await mockIdentity(context)
    await mockAlerts(context, events, shape === 'portrait' ? portrait : evidenceImage, shape === 'portrait' ? 'image/svg+xml' : 'image/png')
    await installFakeSocket(page)
    await page.setViewportSize({ width: shape === 'landscape' ? 1440 : 900, height: 1000 })
    await page.goto(adminPath('/alerts'))
    const thumbnail = page.locator('.evidence-indicator .evidence-image').first()
    await expect(thumbnail.locator('.evidence-box')).toHaveCount(1)
    await page.locator('.alert-event-row').click()
    const detail = page.getByRole('dialog', { name: '未佩戴安全帽' })
    const image = detail.locator('.evidence-image')
    await expect(image.locator('.evidence-box-label')).toHaveText('安全帽 91%')
    async function assertAligned() {
      await expect.poll(async () => image.evaluate((element) => {
        const img = element.querySelector('img')!
        const box = element.querySelector('.evidence-box')!.getBoundingClientRect()
        const bounds = img.getBoundingClientRect()
        const scale = Math.min(bounds.width / img.naturalWidth, bounds.height / img.naturalHeight)
        const w = img.naturalWidth * scale, h = img.naturalHeight * scale
        return Math.max(Math.abs(box.x - bounds.x - (bounds.width - w) / 2 - w * .25),
          Math.abs(box.y - bounds.y - (bounds.height - h) / 2 - h * .25),
          Math.abs(box.width - w * .5), Math.abs(box.height - h * .5))
      })).toBeLessThan(1)
    }
    await assertAligned()
    await image.screenshot({ path: `../evidence/M40/display-${shape}-desktop.png` })
    await page.setViewportSize({ width: 390, height: 844 })
    await assertAligned()
    await expectNoOverflow(page)
    await image.screenshot({ path: `../evidence/M40/display-${shape}-narrow.png` })
    events[0].evidence.displayOverlay.bakedIn = true
    await page.reload()
    await expect(page.locator('.evidence-indicator img')).toBeVisible()
    await expect(page.locator('.evidence-box')).toHaveCount(0)
    await page.locator('.alert-event-row').click()
    await expect(detail.locator('img')).toBeVisible()
    await expect(detail.locator('.evidence-box')).toHaveCount(0)
  })
}

async function expectNoOverflow(page: Page) {
  expect(await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth - window.innerWidth, scrollX: window.scrollX }))).toEqual({ overflow: 0, scrollX: 0 })
}

async function expectAlertRowLayout(page: Page, viewport: 'desktop' | 'mobile') {
  const layout = await page.locator('.alert-event-row').first().evaluate((row) => {
    const grid = row.querySelector<HTMLElement>('.alert-event-grid')
    if (!grid) return null
    const rowRect = row.getBoundingClientRect()
    const gridRect = grid.getBoundingClientRect()
    return {
      display: getComputedStyle(grid).display,
      columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
      row: { left: rowRect.left, right: rowRect.right, width: rowRect.width },
      grid: { left: gridRect.left, right: gridRect.right, width: gridRect.width },
      children: Array.from(grid.children).map((child) => {
        const rect = child.getBoundingClientRect()
        const style = getComputedStyle(child)
        return { left: rect.left, right: rect.right, top: rect.top, width: rect.width, display: style.display, fontSize: style.fontSize, padding: style.padding, text: child.textContent?.trim() ?? '' }
      }),
    }
  })
  expect(layout).not.toBeNull()
  expect(layout!.display).toBe('grid')
  expect(layout!.children).toHaveLength(6)
  expect(layout!.children.map((child, index) => ({ index, width: Math.round(child.width), display: child.display, fontSize: child.fontSize, padding: child.padding, text: child.text })).filter((child) => child.width === 0)).toEqual([])
  expect(layout!.grid.left).toBeGreaterThanOrEqual(layout!.row.left)
  expect(layout!.grid.right).toBeLessThanOrEqual(layout!.row.right)
  if (viewport === 'desktop') {
    expect(layout!.columns).toBe(6)
    for (let index = 1; index < layout!.children.length; index += 1) {
      expect(layout!.children[index].left).toBeGreaterThan(layout!.children[index - 1].left)
    }
  } else {
    expect(layout!.columns).toBe(3)
    expect(layout!.children[1].left).toBeGreaterThan(layout!.children[0].left)
    expect(layout!.children[4].left).toBeGreaterThan(layout!.children[1].left)
  }
}

test('desktop alert workflow filters, cancels safely, disposes and records verification truth', async ({ context, page }) => {
  const events = eventFixtures()
  await mockIdentity(context)
  const calls = await mockAlerts(context, events)
  await installFakeSocket(page)
  const errors = collectErrors(page)
  await page.goto(adminPath('/alerts'))

  await expect(page.locator('.alert-event-row')).toHaveCount(3)
  await expect(page.locator('.evidence-indicator img').first()).toBeVisible()
  await expect(page.locator('.evidence-indicator').first()).toContainText('有证据')
  await expect(page.locator('.disposition-badge').first()).toHaveText('待确认')
  await expect(page.locator('.disposition-badge').first()).toBeVisible()
  await expectAlertRowLayout(page, 'desktop')
  await page.screenshot({ path: '../evidence/M32/M32-T14-alerts-list-desktop.png' })
  await expect(page.getByRole('button', { name: /严重 01/ })).toBeVisible()
  await page.getByRole('button', { name: /严重 01/ }).click()
  await expect(page.locator('.alert-event-row')).toHaveCount(1)
  await page.locator('.alert-event-row').click()

  const detail = page.getByRole('dialog', { name: '未佩戴安全帽' })
  await expect(detail).toBeVisible()
  await expect(detail.getByText('已提级')).toBeVisible()
  await expect(detail.getByRole('img', { name: '未佩戴安全帽事件证据' })).toBeVisible()
  await detail.getByRole('button', { name: '确认告警' }).click()
  const confirmation = page.getByRole('alertdialog', { name: '确认告警' })
  await confirmation.getByRole('button', { name: '取消' }).click()
  expect(calls.dispositionPosts()).toBe(0)

  await detail.getByRole('button', { name: '确认告警' }).click()
  await confirmation.getByRole('button', { name: '确认告警' }).click()
  await expect(detail.getByText('告警已确认。')).toBeVisible()
  expect(calls.dispositionPosts()).toBe(1)
  await detail.getByRole('button', { name: '发起 AI 复核' }).click()
  await expect(detail.locator('.verification-panel')).toContainText('未配置可用的复核供应商或模型')
  expect(calls.verificationPosts()).toBe(1)
  await expectNoOverflow(page)
  await detail.evaluate((element) => { element.scrollTop = 0 })
  await expect(detail.getByRole('heading', { name: '未佩戴安全帽' })).toBeVisible()
  await page.screenshot({ path: '../evidence/M32/M32-T05-alerts-desktop.png' })
  expect(errors).toEqual([])
})

test('narrow alert detail handles missing evidence and false-positive confirmation', async ({ context, page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const events = eventFixtures()
  await mockIdentity(context)
  const calls = await mockAlerts(context, events)
  await installFakeSocket(page)
  const errors = collectErrors(page)
  await page.goto(adminPath('/alerts'))

  await expect(page.locator('.disposition-badge').first()).toBeVisible()
  await expectAlertRowLayout(page, 'mobile')
  await page.screenshot({ path: '../evidence/M32/M32-T14-alerts-list-mobile.png' })
  await page.locator('.alert-event-row').filter({ hasText: '人员进入危险区' }).click()
  const detail = page.getByRole('dialog', { name: '人员进入危险区' })
  await expect(detail.getByText('没有可用证据')).toBeVisible()
  await detail.getByRole('button', { name: '标记误报' }).click()
  await page.getByRole('alertdialog', { name: '确认标记误报' }).getByRole('button', { name: '确认标记' }).click()
  await expect(detail.getByText('已标记为误报。')).toBeVisible()
  expect(calls.dispositionPosts()).toBe(1)
  await expectNoOverflow(page)
  await detail.evaluate((element) => { element.scrollTop = 0 })
  await expect(detail.getByRole('heading', { name: '人员进入危险区' })).toBeVisible()
  await page.screenshot({ path: '../evidence/M32/M32-T05-alerts-mobile.png' })
  expect(errors).toEqual([])
})

test('empty alert storage is explicit and contains no synthetic rows', async ({ context, page }) => {
  await mockIdentity(context)
  await mockAlerts(context, [])
  await installFakeSocket(page)
  await page.goto(adminPath('/alerts'))
  await expect(page.getByText('当前没有告警事件')).toBeVisible()
  await expect(page.locator('.alert-event-row')).toHaveCount(0)
})

test('list failure stays unavailable and retry can recover to an empty truth', async ({ context, page }) => {
  await mockIdentity(context)
  await installFakeSocket(page)
  let attempts = 0
  let unavailable = true
  await context.route('**/aiyoloapi/projects/fixture-project/alerts', async (route) => {
    attempts += 1
    if (unavailable) await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'alerts_unavailable', message: 'database unavailable' } }) })
    else await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ events: [] }) })
  })
  await page.goto(adminPath('/alerts'))
  await expect(page.getByText('告警数据不可用')).toBeVisible()
  unavailable = false
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.getByText('当前没有告警事件')).toBeVisible()
  expect(attempts).toBeGreaterThanOrEqual(2)
})

test('concurrent disposition conflict reloads the current event before allowing another action', async ({ context, page }) => {
  const event = eventFixtures()[0]
  await mockIdentity(context)
  await installFakeSocket(page)
  await context.route('**/aiyoloapi/projects/fixture-project/alerts', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ events: [event] }) }))
  await context.route('**/aiyoloapi/projects/fixture-project/alerts/**/acknowledge', (route) => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'disposition_conflict', message: 'event already updated' } }) }))
  await context.route('**/aiyoloapi/projects/fixture-project/alerts/**/evidence', (route) => route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'evidence_not_found' } }) }))
  await context.route('**/aiyoloapi/projects/fixture-project/alerts/**/verification', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ eventId: event.eventId, status: 'UNREVIEWED', verdict: null }) }))
  let detailReads = 0
  await context.route('**/aiyoloapi/projects/fixture-project/alerts/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith(`/${encodeURIComponent(event.eventId)}`)) {
      detailReads += 1
      const current = detailReads === 1
        ? event
        : { ...event, disposition: { status: 'ACKNOWLEDGED', actor: 'other-admin', actedAtUs: 1_750_000_210_000_000 } }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(current) })
    }
    return route.fallback()
  })
  await page.goto(adminPath('/alerts'))
  await page.locator('.alert-event-row').click()
  const detail = page.getByRole('dialog', { name: '未佩戴安全帽' })
  await detail.getByRole('button', { name: '确认告警' }).click()
  await page.getByRole('alertdialog', { name: '确认告警' }).getByRole('button', { name: '确认告警' }).click()
  await expect(detail.getByText('事件已被其他操作更新；详情已刷新，请核对最新状态后重试。')).toBeVisible()
  await expect(detail.locator('.disposition-badge')).toHaveText('已确认')
  await expect(detail.getByRole('button', { name: '已确认' })).toBeDisabled()
  expect(detailReads).toBe(2)
})
