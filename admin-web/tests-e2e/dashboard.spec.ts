import { adminPath, selectElementOption } from './helpers/navigation'
import { fixtureUser, fixtureProjects, fixtureProject, unscopedPath } from './helpers/project-fixture'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { statsFixture } from '../tests/fixtures/dashboard'
import type { StatsRange } from '../src/features/dashboard/types'
const image = readFileSync(resolve(process.cwd(), 'tests-e2e/fixtures/evidence_helmet_violation.png'))
const event = { eventId: 'event-01', displayName: '入口未戴安全帽', sourceId: 'gate', confirmedAtUs: 1791518400123456, severity: 'CRITICAL', disposition: { status: 'OPEN' } }
function streamFixtures() {
  return Array.from({ length: 5 }, (_, i) => ({ stream_id: `cam-${i}`, display_name: ['北门摄像机', '西侧通道', '卸货区域', '移动巡检', '第五路'][i], source_url: 'rtsp://secret:private@camera/live', enabled: i !== 1, runtime_available: i !== 1, yolo_enabled: true, received_fps: 20, frames_received: 999, runtime_state: i === 1 ? 'disabled' : 'running' }))
}
async function service(context: BrowserContext, options: { empty?: boolean; statsFailure?: boolean; alertsFailure?: boolean; streamsFailure?: boolean } = {}) {
  const state = { reads: 0, previews: [] as string[], streams: options.empty ? [] : streamFixtures() }
  await context.route('**/aiyoloapi/**', route => {
    const url = new URL(route.request().url()), path = unscopedPath(url.pathname)
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: { username: 'test-admin', role: 'admin' } })
    if (path.endsWith('/auth/me')) return reply(fixtureUser())
    if (path.endsWith('/auth/projects')) return reply(fixtureProjects())
    if (path === '/aiyoloapi') return reply(fixtureProject)
    if (path.endsWith('/verification')) return reply({ status: 'UNREVIEWED' })
    if (path.endsWith('/dashboard/stats')) { state.reads++; return options.statsFailure ? reply({ detail: '统计仓储不可用' }, 503) : reply(statsFixture(url.searchParams.get('range') as StatsRange, options.empty ? 0 : 12)) }
    if (path.endsWith('/streams')) return options.streamsFailure ? reply({ detail: '流接口故障' }, 503) : reply(state.streams)
    if (path.endsWith('/alerts')) return options.alertsFailure ? reply({ detail: '告警接口故障' }, 503) : reply({ events: options.empty ? [] : [event] })
    if (path.endsWith('/alerts/event-01')) return reply(event)
    if (path.endsWith('/preview')) { state.previews.push(path); return route.fulfill({ contentType: 'image/jpeg', body: image }) }
    if (path.endsWith('/models')) return reply({ models: [] })
    return reply({}, 404)
  })
  return state
}
async function noOverlap(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const rectangles = await page.locator('.board-grid > .board-panel').evaluateAll(nodes => nodes.map(node => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom } }))
  for (let i = 0; i < rectangles.length; i++) for (let j = i + 1; j < rectangles.length; j++) {
    const a = rectangles[i]!, b = rectangles[j]!
    expect(a.x < b.right - 1 && b.x < a.right - 1 && a.y < b.bottom - 1 && b.y < a.bottom - 1).toBe(false)
  }
}
test('dashboard renders real fields and project stream status without a video wall', async ({ context, page }) => {
  const state = await service(context); await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto(adminPath('/dashboard'))
  await expect(page.locator('.board-kpis')).toContainText('12'); await expect(page.locator('.board-video-wall')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '现场流状态' })).toBeVisible()
  expect(state.previews).toHaveLength(0)
  await expect(page.locator('.board-resources')).toHaveCount(0)
  await expect(page.locator('.board-stream-list li').nth(1)).toContainText('已停用')
  await expect(page.locator('.operations-board')).not.toContainText('rtsp://secret')
  await noOverlap(page); await page.screenshot({ path: '../evidence/M34/M34-T03-dashboard-desktop.png', fullPage: true })
  await selectElementOption(page, '统计周期', '近 7 天'); await expect(page).toHaveURL(/range=7d/); await expect(page.locator('.trend-bucket')).toHaveCount(7)
  await selectElementOption(page, '统计周期', '近 30 天'); await expect(page.locator('.trend-bucket')).toHaveCount(6)
  expect(state.previews).toHaveLength(0)
  await page.locator('.board-alert').click(); await expect(page).toHaveURL(/alerts\?event=event-01/)
  await expect(page.getByRole('dialog')).toContainText('入口未戴安全帽')
})
test('fast range switching never replaces newer data with an older response', async ({ context, page }) => {
  await service(context)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await context.route('**/aiyoloapi/projects/fixture-project/dashboard/stats?range=today', async route => { await gate; await route.fulfill({ contentType: 'application/json', body: JSON.stringify(statsFixture('today', 99)) }).catch(() => {}) })
  await page.goto(adminPath('/dashboard')); await selectElementOption(page, '统计周期', '近 30 天')
  await expect(page.locator('.board-kpis')).toContainText('12'); release()
  await expect(page.locator('.trend-bucket')).toHaveCount(6); await expect(page.locator('.board-kpis')).not.toContainText('99')
})
test('empty data remains zero and overview opens the actual create flow', async ({ context, page }) => {
  await service(context, { empty: true }); await page.goto(adminPath('/overview'))
  await expect(page.locator('.board-kpis article').first().locator('strong')).toHaveText('0')
  await expect(page.getByText('暂无有效响应样本')).toBeVisible(); await expect(page.getByText('当前没有视频流会话')).toBeVisible()
  await expect(page.locator('.board-video-wall')).toHaveCount(0)
  await page.screenshot({ path: '../evidence/M34/M34-T03-overview-empty.png', fullPage: true })
  await page.getByRole('link', { name: '新建视频流' }).click(); await expect(page.getByLabel('流 ID', { exact: true })).toBeVisible()
})
test('statistics failure does not fabricate zeroes or hide working streams and alerts', async ({ context, page }) => {
  await service(context, { statsFailure: true }); await page.goto(adminPath('/dashboard'))
  await expect(page.getByRole('status')).toContainText('统计仓储不可用'); await expect(page.locator('.board-kpis article').first().locator('strong')).toHaveText('—')
  await expect(page.locator('.board-alert')).toHaveCount(1); await expect(page.locator('.board-video-wall')).toHaveCount(0)
})
test('source failures remain unavailable independently and polling recovers', async ({ context, page }) => {
  await service(context, { alertsFailure: true, streamsFailure: true }); await page.goto(adminPath('/dashboard'))
  await expect(page.locator('.board-kpis')).toContainText('12'); await expect(page.getByText('告警不可用：告警接口故障')).toBeVisible(); await expect(page.getByText('视频流不可用：流接口故障')).toBeVisible()
  await expect(page.locator('.board-video-wall')).toHaveCount(0)
  await context.unroute('**/aiyoloapi/**'); await service(context)
  await page.getByRole('button', { name: '刷新看板' }).click(); await expect(page.locator('.board-stream-list li')).toHaveCount(5)
})
test('fullscreen, escape and denied fullscreen restore focus and scrolling on narrow screens', async ({ context, page }) => {
  await service(context); await page.setViewportSize({ width: 1920, height: 1080 }); await page.goto(adminPath('/dashboard'))
  await page.getByRole('button', { name: '大屏模式' }).click(); await expect(page.locator('.operations-board')).toHaveClass(/is-focused/)
  await noOverlap(page); await page.screenshot({ path: '../evidence/M34/M34-T03-dashboard-screen.png', fullPage: true })
  await page.keyboard.press('Escape'); await expect(page.locator('.operations-board')).not.toHaveClass(/is-focused/)
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('')
  await expect(page.getByRole('button', { name: '大屏模式' })).toBeFocused()
  await page.evaluate(() => { HTMLElement.prototype.requestFullscreen = () => Promise.reject(new Error('denied')) })
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(250); await noOverlap(page)
  await page.screenshot({ path: '../evidence/M34/M34-T03-dashboard-narrow.png', fullPage: true })
  await page.getByRole('button', { name: '大屏模式' }).click(); await noOverlap(page)
  await page.getByRole('button', { name: '退出大屏' }).click(); await expect(page.locator('.operations-board')).not.toHaveClass(/is-focused/)
  await page.getByRole('button', { name: '大屏模式' }).click(); await page.locator('.board-panel').getByRole('link', { name: '诊断 →' }).click()
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('')
})
test('dashboard polling never opens live video previews', async ({ context, page }) => {
  const state = await service(context)
  await page.goto(adminPath('/dashboard')); await expect(page.locator('.board-stream-list li')).toHaveCount(5)
  await expect.poll(() => state.reads, { timeout: 14000 }).toBeGreaterThan(1)
  expect(state.previews).toHaveLength(0)
  await expect(page.getByRole('link', { name: '管理视频流 →' })).toBeVisible()
})
