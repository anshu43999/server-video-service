import { expect, test, type BrowserContext, type Page, type WebSocketRoute } from '@playwright/test'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'
import type { AlertEvent } from '../src/features/alerts/types'
import type { AccessibleProject } from '../src/api/projects'

const event = (id: string, projectId = fixtureProject.projectId): AlertEvent => ({
  eventId: id, projectId, displayName: id, origin: 'SERVER_STREAM', streamId: 'camera',
  state: 'CONFIRMED', confirmedAtUs: 123, disposition: { status: 'OPEN' },
})
async function service(context: BrowserContext) {
  const state = {
    events: [] as AlertEvent[], reads: [] as string[], writes: [] as string[],
    sockets: [] as WebSocketRoute[], projects: [fixtureProject] as AccessibleProject[], listStatus: 200,
    gate: undefined as Promise<void> | undefined,
  }
  await context.route('**/aiyoloapi/**', async route => {
    const path = new URL(route.request().url()).pathname
    ;(route.request().method() === 'GET' ? state.reads : state.writes).push(path)
    const reply = (json: unknown, status = 200) => route.fulfill({ json, status }).catch(() => {})
    if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false })
    if (path.endsWith('/auth/me')) return reply(fixtureUser())
    if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: state.projects })
    const project = state.projects.find(p => path === '/aiyoloapi/projects/' + p.projectId)
    if (project) return reply(project)
    if (path.endsWith('/metrics')) return reply({ scope: 'project', projectId: path.split('/')[3], streams: { total: 0, framesReceived: 0, framesProcessed: 0, framesDropped: 0 } })
    if (path.endsWith('/alerts')) {
      // Capture at request entry to expose a genuinely stale in-flight snapshot.
      const snapshot = state.events.filter(e => e.projectId === path.split('/')[3]).map(e => ({ ...e }))
      const status = state.listStatus
      await state.gate
      return reply(status === 200 ? { events: snapshot } : { detail: 'isolated list failure' }, status)
    }
    return reply({ detail: 'isolated endpoint not found' }, 404)
  })
  await context.routeWebSocket('**/aiyoloapi/**', socket => { state.sockets.push(socket); socket.onMessage(() => {}) })
  return state
}
const count = (state: Awaited<ReturnType<typeof service>>, suffix = '/alerts') => state.reads.filter(path => path.endsWith(suffix)).length
async function start(page: Page, state: Awaited<ReturnType<typeof service>>, simulated = true) {
  if (simulated) {
    const time = new Date('2026-11-09T10:00:00Z')
    await page.clock.install({ time }); await page.clock.pauseAt(time)
  }
  await page.goto('/admin-next/project-diagnostics?project=' + fixtureProject.projectId)
  await expect(page.getByRole('heading', { name: '当前项目运行汇总' })).toBeVisible()
  await expect.poll(() => state.sockets.length).toBe(1)
  await expect.poll(() => count(state)).toBe(2) // baseline, then WS handshake catch-up
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert', '')
}
async function advance(page: Page, milliseconds: number) {
  while (milliseconds > 0) {
    const step = Math.min(1000, milliseconds)
    await page.clock.runFor(step)
    await expect(page.locator('#main-content')).not.toHaveAttribute('inert', '')
    milliseconds -= step
  }
}
async function record(page: Page, state: Awaited<ReturnType<typeof service>>, scenario: string, extra = {}) {
  const timing = await page.evaluate(() => performance.getEntriesByType('resource')
    .filter(e => new URL(e.name).pathname.startsWith('/aiyoloapi/'))
    .map(e => ({ path: new URL(e.name).pathname, startMs: e.startTime, durationMs: e.duration })))
  const result = { scenario, environment: 'real local Chromium; isolated API/WS fixtures; not production latency',
    counts: Object.fromEntries([...new Set(state.reads)].map(p => [p, state.reads.filter(path => path === p).length])),
    sockets: state.sockets.length, writes: state.writes, ...extra }
  console.log(JSON.stringify(result))
  await test.info().attach(scenario, { body: JSON.stringify({ ...result, timing }, null, 2), contentType: 'application/json' })
}

test('real 60.5s healthy connection retains twelve REST compensation reads and four permission checks', async ({ context, page }) => {
  test.setTimeout(90_000)
  const state = await service(context); await start(page, state, false)
  const before = { alerts: count(state), me: count(state, '/auth/me'), projects: count(state, '/auth/projects') }
  await page.waitForTimeout(60_500)
  const delta = { alerts: count(state) - before.alerts, me: count(state, '/auth/me') - before.me, projects: count(state, '/auth/projects') - before.projects }
  expect(delta).toEqual({ alerts: 12, me: 4, projects: 4 })
  expect(state.sockets).toHaveLength(1); expect(state.writes).toEqual([])
  await record(page, state, 'real-60s-alert-compensation', { delta, slowCompensationEnabled: false })
})

test('simulated healthy socket still recovers missed events and REST failures without duplicate notices', async ({ context, page }) => {
  const state = await service(context); await start(page, state)
  state.listStatus = 503
  state.events = [event('missed-by-ws')]
  await advance(page, 5100); await expect.poll(() => count(state)).toBe(3)
  await expect(page.locator('.project-alert-notices')).toHaveCount(0)
  state.listStatus = 200
  await advance(page, 5100)
  await expect(page.locator('.project-alert-notices')).toContainText('missed-by-ws')
  state.sockets[0].send(JSON.stringify({ type: 'alert', event: state.events[0] }))
  await expect(page.locator('.project-alert-notices').getByText('新告警：missed-by-ws', { exact: true })).toHaveCount(1)
  await record(page, state, 'simulated-missed-and-error-recovery')
})

test('real disconnect reconciles immediately and reconnect replay does not duplicate notifications', async ({ context, page }) => {
  const state = await service(context); await start(page, state, false)
  state.events = [event('disconnect-recovery')]
  const started = Date.now()
  state.sockets[0].close({ code: 1011, reason: 'isolated transport failure' })
  await expect(page.locator('.project-alert-notices')).toContainText('disconnect-recovery')
  const recoveryMs = Date.now() - started
  expect(recoveryMs).toBeLessThan(5000)
  await expect.poll(() => state.sockets.length).toBe(2)
  await expect.poll(() => count(state)).toBe(4)
  state.sockets[1].send(JSON.stringify({ type: 'alert', event: state.events[0] }))
  await expect(page.locator('.project-alert-notices').getByText('新告警：disconnect-recovery', { exact: true })).toHaveCount(1)
  await record(page, state, 'real-disconnect-reconnect', { recoveryMs })
})

test('simulated reconnect during pending REST gets one fresh trailing snapshot without parallel reads', async ({ context, page }) => {
  const state = await service(context); await start(page, state)
  let release!: () => void; state.gate = new Promise(resolve => { release = resolve })
  await advance(page, 5100); await expect.poll(() => count(state)).toBe(3)
  state.events = [event('created-during-flight')]
  state.sockets[0].close({ code: 1011 })
  // Wait for the browser close event before advancing its reconnect clock.
  await page.waitForTimeout(100)
  await advance(page, 1000); await expect.poll(() => state.sockets.length).toBe(2)
  await advance(page, 2000)
  expect(count(state)).toBe(3)
  state.gate = undefined; release()
  await expect(page.locator('.project-alert-notices')).toContainText('created-during-flight')
  expect(count(state)).toBe(4)
  await record(page, state, 'simulated-trailing-reconciliation', { readsWhilePending: 1, trailingReads: 1 })
})

test('revocation cancels pending alert REST and queued recovery without leaking old notices', async ({ context, page }) => {
  const state = await service(context); await start(page, state)
  const cancelled: string[] = []
  page.on('requestfailed', request => { if (request.url().endsWith('/alerts')) cancelled.push(request.failure()?.errorText ?? '') })
  state.events = [event('must-never-render')]
  let release!: () => void; state.gate = new Promise(resolve => { release = resolve })
  await advance(page, 5100); await expect.poll(() => count(state)).toBe(3)
  state.projects = [{ ...state.projects[0], membershipRevision: 2 }]
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.getByRole('alert')).toContainText('项目状态或成员权限已变化')
  await expect.poll(() => cancelled.length).toBe(1)
  expect(cancelled[0]).toContain('ERR_ABORTED')
  state.gate = undefined; release()
  await page.clock.runFor(10_000)
  expect(count(state)).toBe(3)
  await expect(page.locator('.project-alert-notices')).toHaveCount(0)
  await record(page, state, 'revocation-cancels-alert-read', { cancelled })
})

test('terminal socket authorization failure stops compensation and closes project', async ({ context, page }) => {
  const state = await service(context); await start(page, state)
  state.sockets[0].close({ code: 4403, reason: 'isolated revoked membership' })
  await expect(page.getByRole('heading', { name: '当前项目运行汇总' })).toHaveCount(0)
  const before = count(state)
  await page.clock.runFor(10_000)
  expect(count(state)).toBe(before)
  expect(state.sockets).toHaveLength(1)
  await record(page, state, 'terminal-authorization-failure')
})

test('project switch rejects wrong-project WS messages and old-project snapshots', async ({ context, page }) => {
  const state = await service(context); await start(page, state)
  state.sockets[0].send(JSON.stringify({ type: 'alert', event: event('wrong-project', 'b') }))
  await expect(page.locator('.project-alert-notices')).toHaveCount(0)
  state.events = [event('old-project-secret')]
  let release!: () => void; state.gate = new Promise(resolve => { release = resolve })
  await advance(page, 5100); await expect.poll(() => count(state)).toBe(3)
  state.projects.push({ ...state.projects[0], projectId: 'b', projectCode: 'b', displayName: '项目 B' })
  await page.evaluate(() => { window.history.pushState({}, '', '/admin-next/project-diagnostics?project=b'); window.dispatchEvent(new PopStateEvent('popstate')) })
  await expect(page.getByRole('region', { name: '当前项目上下文' })).toContainText('项目 B')
  state.gate = undefined; release()
  await expect.poll(() => state.sockets.length).toBe(2)
  state.sockets[1].send(JSON.stringify({ type: 'alert', event: event('new-project-visible', 'b') }))
  await expect(page.locator('.project-alert-notices')).toContainText('new-project-visible')
  await expect(page.locator('.project-alert-notices')).not.toContainText('old-project-secret')
  await record(page, state, 'project-switch-isolation')
})
