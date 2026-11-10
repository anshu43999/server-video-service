import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'
import type { ConversionJob } from '../src/features/models/types'
import type { DeliveryStatus } from '../src/features/operations/api'

const job = (status: ConversionJob['status']): ConversionJob => ({ id: 'poll-job', action: 'inspect', status, attempt: 1, created_at: 1, metadata: { name: '隔离轮询任务' } })
const config = { mode: 'local', distribution: 'Ubuntu', python_path: 'python', input_size: 640, calibration_data: '', default_calibration_dataset_id: '', timeout_seconds: 1800, auto_convert: false, remote_endpoint: '', remote_token_env: 'TOKEN_ENV', remote_allow_insecure_http: false, remote_poll_interval_seconds: 2, remote_verifier_mode: 'local' }
async function service(context: BrowserContext) {
  const state = {
    jobs: [] as ConversionJob[], jobStatus: 200, deliveryStatus: 200, writeStatus: 202,
    delivery: { channels: { app: { enabled: true, subscribers: 1 } }, pending: 0, recent: [] } as DeliveryStatus,
    gate: undefined as Promise<void> | undefined, reads: [] as string[], writes: [] as string[],
  }
  await context.route('**/aiyoloapi/**', async route => {
    const path = new URL(route.request().url()).pathname
    ;(route.request().method() === 'GET' ? state.reads : state.writes).push(path)
    const reply = (json: unknown, status = 200) => route.fulfill({ json, status }).catch(() => {})
    if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false })
    if (path.endsWith('/auth/me')) return reply(fixtureUser())
    if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [fixtureProject] })
    if (path === '/aiyoloapi/projects/' + fixtureProject.projectId) return reply(fixtureProject)
    if (path.endsWith('/conversion/config')) return reply({ config, max_upload_bytes: 1000, supported_modes: ['local'] })
    if (path.endsWith('/conversion/calibration-datasets')) return reply({ datasets: [], max_upload_bytes: 1000 })
    if (path.endsWith('/conversion/jobs')) { await state.gate; return reply(state.jobStatus === 200 ? { jobs: state.jobs } : { detail: 'isolated failure ' + count(state, '/conversion/jobs') }, state.jobStatus) }
    if (path.endsWith('/models')) return reply({ models: [] })
    if (path.endsWith('/alerts')) return reply({ events: [] })
    if (path.endsWith('/delivery/policy')) return reply({ revision: 1, enabled: true, minimumSeverity: 'MINOR', channels: ['app'] })
    if (path.endsWith('/alerts/delivery/status')) return reply(state.deliveryStatus === 200 ? state.delivery : { detail: 'isolated failure' }, state.deliveryStatus)
    if (path.endsWith('/test-delivery')) return reply(state.writeStatus === 202 ? { accepted: true, deliveryIds: ['delivery-test'] } : { detail: 'uncertain write' }, state.writeStatus)
    return reply({ detail: 'fixture endpoint not found' }, 404)
  })
  await context.routeWebSocket('**/aiyoloapi/**', socket => { socket.onMessage(() => {}) })
  return state
}
const count = (state: Awaited<ReturnType<typeof service>>, suffix: string) => state.reads.filter(path => path.endsWith(suffix)).length
async function evidence(page: Page, state: Awaited<ReturnType<typeof service>>, scenario: string, extra: Record<string, unknown> = {}) {
  const timing = await page.evaluate(() => performance.getEntriesByType('resource').filter(e => new URL(e.name).pathname.startsWith('/aiyoloapi/')).map(e => { const r = e as PerformanceResourceTiming; return { path: new URL(r.name).pathname, startMs: r.startTime, durationMs: r.duration, transferBytes: r.transferSize, initiator: r.initiatorType } }))
  const result = { scenario, environment: 'local Chromium with isolated API fixtures; not production performance', counts: Object.fromEntries([...new Set(state.reads)].map(path => [path, state.reads.filter(p => p === path).length])), writes: state.writes, ...extra }
  console.log(JSON.stringify(result))
  await test.info().attach(scenario, { body: JSON.stringify({ ...result, timing }), contentType: 'application/json' })
}
async function clock(page: Page) {
  const time = new Date('2026-11-09T10:00:00Z')
  await page.clock.install({ time }); await page.clock.pauseAt(time)
}
async function visible(page: Page, value: boolean) {
  await page.evaluate(value => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: value ? 'visible' : 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
  }, value)
}
async function advance(page: Page, milliseconds: number) {
  // Network responses use real time. A single 30s virtual jump would expire
  // the unrelated 15s permission request before its local fixture can reply.
  while (milliseconds > 0) {
    const step = Math.min(milliseconds, 1000)
    await page.clock.runFor(step)
    await expect(page.locator('#main-content')).not.toHaveAttribute('inert', '')
    milliseconds -= step
  }
}

test('real 60.5s push idle has two status reads and zero policy reloads', async ({ context, page }) => {
  test.setTimeout(90000)
  const state = await service(context); await page.goto('/admin-next/push?project=' + fixtureProject.projectId)
  await expect(page.getByRole('heading', { name: '通道运行状态' })).toBeVisible()
  const before = { status: count(state, '/delivery/status'), policy: count(state, '/delivery/policy'), me: count(state, '/auth/me'), projects: count(state, '/auth/projects') }
  await page.waitForTimeout(60500)
  const delta = { status: count(state, '/delivery/status') - before.status, policy: count(state, '/delivery/policy') - before.policy, me: count(state, '/auth/me') - before.me, projects: count(state, '/auth/projects') - before.projects }
  expect(delta).toEqual({ status: 2, policy: 0, me: 4, projects: 4 })
  expect(state.writes).toEqual([])
  await evidence(page, state, 'real-push-idle-60s', { delta })
})

test('real active jobs update every 3s and completion refreshes models once', async ({ context, page }) => {
  const state = await service(context); state.jobs = [job('running')]
  await page.goto('/admin-next/models?pane=upload'); await expect(page.locator('.conversion-job')).toHaveCount(1)
  const before = count(state, '/conversion/jobs')
  await page.waitForTimeout(9300)
  const activeReads = count(state, '/conversion/jobs') - before
  expect(activeReads).toBe(3)
  state.jobs = [job('succeeded')]
  await page.getByRole('button', { name: '刷新任务', exact: true }).click()
  await expect.poll(() => count(state, '/models')).toBe(2)
  const after = count(state, '/conversion/jobs'); await page.waitForTimeout(3200)
  expect(count(state, '/conversion/jobs')).toBe(after)
  await evidence(page, state, 'real-active-jobs-9s', { activeReads })
})

test('simulated visibility cancels a pending jobs read and resumes exactly once', async ({ context, page }) => {
  const state = await service(context); await clock(page)
  await page.goto('/admin-next/models?pane=upload'); await expect(page.getByText('暂无任务。', { exact: false })).toBeVisible()
  let release!: () => void; state.gate = new Promise(resolve => { release = resolve })
  const failures: string[] = []
  page.on('requestfailed', request => { if (request.url().endsWith('/conversion/jobs')) failures.push(request.failure()?.errorText ?? '') })
  await page.getByRole('button', { name: '刷新任务', exact: true }).click(); await expect.poll(() => count(state, '/conversion/jobs')).toBe(2)
  await visible(page, false); await expect.poll(() => failures.length).toBe(1)
  await page.clock.runFor(60000); expect(count(state, '/conversion/jobs')).toBe(2)
  release(); state.gate = undefined
  await visible(page, true); await expect.poll(() => count(state, '/conversion/jobs')).toBe(3)
  await expect(page.getByText('当前任务状态可能已过期', { exact: false })).toHaveCount(0)
  expect(failures[0]).toContain('ERR_ABORTED')
  await evidence(page, state, 'simulated-hide-resume', { failures })
})

test('simulated clock checks 5/10/20/30s backoff and successful recovery', async ({ context, page }) => {
  const state = await service(context); await clock(page); state.jobStatus = 503
  await page.goto('/admin-next/models?pane=upload'); await expect(page.getByText('isolated failure 1', { exact: false })).toBeVisible()
  for (const [i, ms] of [5000, 10000, 20000, 30000].entries()) {
    await advance(page, ms - 1); expect(count(state, '/conversion/jobs')).toBe(i + 1)
    await advance(page, 1); await expect.poll(() => count(state, '/conversion/jobs')).toBe(i + 2)
    // Wait for this response's UI update, not the previous error text. Network
    // completion schedules the next delay; advancing before it would skew time.
    await expect(page.getByText('isolated failure ' + (i + 2), { exact: false })).toBeVisible()
  }
  state.jobStatus = 200; await page.getByRole('button', { name: '刷新任务', exact: true }).click()
  await expect(page.getByText('当前任务状态可能已过期', { exact: false })).toHaveCount(0)
  expect(state.writes).toEqual([])
  await evidence(page, state, 'simulated-backoff')
})

test('push pending and explicit test use fast reads without policy reload or write replay', async ({ context, page }) => {
  const state = await service(context); state.delivery.pending = 1; await clock(page)
  await page.goto('/admin-next/push?project=' + fixtureProject.projectId)
  await expect(page.getByRole('heading', { name: '通道运行状态' })).toBeVisible()
  await page.clock.runFor(5000); await expect.poll(() => count(state, '/delivery/status')).toBe(2)
  await page.getByRole('button', { name: '测试 移动端通知', exact: true }).click()
  await page.getByRole('button', { name: '确认发送测试', exact: true }).click()
  await expect(page.getByText('测试回执尚未确认', { exact: false })).toBeVisible()
  expect(state.writes).toHaveLength(1); expect(count(state, '/delivery/policy')).toBe(1)
  state.delivery.pending = 0
  state.delivery.recent = [{ delivery_id: 'delivery-test', channel: 'app', status: 'failed', attempts: 3 }]
  await page.clock.runFor(5000); await expect(page.getByText('测试回执尚未确认', { exact: false })).toHaveCount(0)
  const reads = count(state, '/delivery/status')
  await advance(page, 29999); expect(count(state, '/delivery/status')).toBe(reads)
  await advance(page, 1); await expect.poll(() => count(state, '/delivery/status')).toBe(reads + 1)
  expect(state.writes).toHaveLength(1); expect(count(state, '/delivery/policy')).toBe(1)
  await evidence(page, state, 'simulated-push-test')
})

test('uncertain explicit delivery write never replays and status failures recover', async ({ context, page }) => {
  const state = await service(context); await clock(page)
  await page.goto('/admin-next/push?project=' + fixtureProject.projectId)
  await expect(page.getByRole('heading', { name: '通道运行状态' })).toBeVisible()
  state.writeStatus = 503; state.deliveryStatus = 503
  await page.getByRole('button', { name: '测试 移动端通知', exact: true }).click()
  await page.getByRole('button', { name: '确认发送测试', exact: true }).click()
  await expect(page.getByText('不会自动重试', { exact: false })).toBeVisible()
  await page.clock.runFor(5000); await expect.poll(() => count(state, '/delivery/status')).toBe(3)
  state.deliveryStatus = 200
  await page.clock.runFor(10000); await expect(page.getByRole('heading', { name: '通道运行状态' })).toBeVisible()
  expect(state.writes).toHaveLength(1); expect(count(state, '/delivery/policy')).toBe(1)
  await evidence(page, state, 'uncertain-test-no-replay')
})
