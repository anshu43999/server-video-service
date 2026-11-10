import { expect, test, type BrowserContext, type Page, type Request } from '@playwright/test'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'
import { statsFixture } from '../tests/fixtures/dashboard'
import type { StatsRange } from '../src/features/dashboard/types'

// All API/WS responses are synthetic. The clock and Chromium networking are real.
const project = { ...fixtureProject, capabilities: [...fixtureProject.capabilities, 'project.members.manage'] }
async function service(context: BrowserContext) {
  const unexpected: string[] = []
  await context.route('**/aiyoloapi/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    const reply = (json: unknown) => route.fulfill({ json })
    if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false })
    if (path.endsWith('/auth/me')) return reply(fixtureUser())
    if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: [project] })
    if (path === '/aiyoloapi/projects/' + project.projectId) return reply(project)
    if (path.endsWith('/members')) return reply({ members: [{ projectId: project.projectId, accountId: 'member-one', username: '验收成员', accountEnabled: true, projectRole: 'PROJECT_USER', enabled: true, revision: 1 }] })
    if (path.endsWith('/dashboard/stats')) return reply(statsFixture(url.searchParams.get('range') as StatsRange, 12))
    if (path.endsWith('/streams')) return reply([])
    if (path.endsWith('/alerts')) return reply({ events: [] })
    unexpected.push(path)
    return route.fulfill({ status: 404, json: { detail: 'isolated unknown endpoint' } })
  })
  await context.routeWebSocket('**/aiyoloapi/**', socket => { socket.onMessage(() => {}) })
  return unexpected
}
type Category = 'permission' | 'business' | 'polling' | 'image'
type Row = { phase: string; method: string; path: string; category: Category;
  startMs: number; endMs?: number; durationMs?: number; status?: number;
  outcome: 'pending' | 'completed' | 'cancelled' | 'network-failure'; failureReason?: string }
function observer(page: Page) {
  let phase = 'initial'
  const phaseNames = new Set([phase])
  const started = Date.now(), rows: Row[] = [], requests = new Map<Request, Row>()
  const websocketPhases: string[] = []
  page.on('websocket', () => websocketPhases.push(phase))
  page.on('request', request => {
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/aiyoloapi/')) return
    // Keep only allowlisted query values, never bodies, headers or credentials.
    const query = new URLSearchParams()
    for (const key of ['limit', 'range']) {
      const value = url.searchParams.get(key)
      if (value && /^(20|100|200|today|7d|30d)$/.test(value)) query.set(key, value)
    }
    const path = url.pathname.replace(project.projectId, ':project') + (query.size ? '?' + query : '')
    const category: Category = request.resourceType() === 'image' ? 'image'
      : url.pathname.includes('/auth/') || url.pathname === '/aiyoloapi/projects/' + project.projectId ? 'permission'
        : url.pathname.endsWith('/alerts') && !url.searchParams.has('limit') ? 'polling' : 'business'
    const row: Row = { phase, method: request.method(), path, category, startMs: Date.now() - started, outcome: 'pending' }
    rows.push(row); requests.set(request, row)
  })
  page.on('response', response => { const row = requests.get(response.request()); if (row) row.status = response.status() })
  page.on('requestfinished', request => {
    const row = requests.get(request); if (!row) return
    row.endMs = Date.now() - started; row.durationMs = row.endMs - row.startMs; row.outcome = 'completed'
  })
  page.on('requestfailed', request => {
    const row = requests.get(request); if (!row) return
    row.endMs = Date.now() - started; row.durationMs = row.endMs - row.startMs
    const aborted = request.failure()?.errorText.includes('ERR_ABORTED')
    row.outcome = aborted ? 'cancelled' : 'network-failure'
    row.failureReason = aborted ? 'browser-aborted' : 'browser-network-failure'
  })
  return {
    rows, setPhase(value: string) { phase = value; phaseNames.add(value) },
    count(name: string, suffix: string) { return rows.filter(r => r.phase === name && r.path.endsWith(suffix)).length },
    async save(name: string, elapsedMs?: number) {
      const resources = await page.evaluate(() => performance.getEntriesByType('resource')
        .filter(e => new URL(e.name).pathname.startsWith('/aiyoloapi/')).map(e => {
          const r = e as PerformanceResourceTiming
          return { path: new URL(r.name).pathname.replace('fixture-project', ':project'), startMs: r.startTime,
            durationMs: r.duration, transferBytes: r.transferSize, initiator: r.initiatorType }
        }))
      const phases = Object.fromEntries([...phaseNames].map(p => {
        const selected = rows.filter(r => r.phase === p)
        return [p, { total: selected.length,
          ...Object.fromEntries(['permission', 'business', 'polling', 'image'].map(c => [c, selected.filter(r => r.category === c).length])),
          cancelled: selected.filter(r => r.outcome === 'cancelled').length,
          networkFailure: selected.filter(r => r.outcome === 'network-failure').length,
          httpError: selected.filter(r => (r.status ?? 0) >= 400).length,
          pending: selected.filter(r => r.outcome === 'pending').length,
          websocketOpened: websocketPhases.filter(v => v === p).length,
          endpoints: Object.fromEntries([...new Set(selected.map(r => r.path))].map(path => [path, selected.filter(r => r.path === path).length])) }]
      }))
      expect(rows.filter(r => r.outcome === 'network-failure' || (r.status ?? 0) >= 400)).toEqual([])
      const result = { scenario: name, environment: 'real local Chromium / real wall clock / synthetic API and WS; not production',
        elapsedMs, phases, notes: ['No populated image scenario in this fixture; image zero is not media acceptance.',
          'Transfer sizes and timings describe intercepted fixture traffic, not backend or production latency.'], rows, resources }
      console.log(JSON.stringify({ scenario: name, elapsedMs, phases }))
      await test.info().attach(name, { body: JSON.stringify(result, null, 2), contentType: 'application/json' })
    },
  }
}
async function navigate(page: Page, path: string) {
  await page.evaluate(path => { window.history.pushState({}, '', path); window.dispatchEvent(new PopStateEvent('popstate')) }, '/admin-next/' + path + '?project=' + project.projectId)
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert', '')
}

test('segmented initial and real 60-second static list retains safe five-second alert compensation', async ({ context, page }) => {
  test.setTimeout(90_000)
  const unexpected = await service(context), observed = observer(page)
  await page.goto('/admin-next/members?project=' + project.projectId)
  await expect(page.getByRole('heading', { name: '验收成员', exact: true })).toBeVisible()
  await expect.poll(() => observed.count('initial', '/alerts')).toBeGreaterThanOrEqual(1)
  await page.waitForTimeout(200)
  expect(observed.count('initial', '/members')).toBe(1)
  expect(observed.count('initial', '/platform/accounts')).toBe(0)
  observed.setPhase('idle-60s'); const start = Date.now()
  await page.waitForTimeout(60_500); const elapsedMs = Date.now() - start
  expect(elapsedMs).toBeGreaterThanOrEqual(60_000)
  expect(observed.count('idle-60s', '/auth/me')).toBe(4)
  expect(observed.count('idle-60s', '/auth/projects')).toBe(4)
  expect(observed.count('idle-60s', '/members')).toBe(0)
  const alerts = observed.count('idle-60s', '/alerts')
  expect(alerts).toBeGreaterThanOrEqual(11); expect(alerts).toBeLessThanOrEqual(13)
  expect(unexpected).toEqual([])
  await observed.save('static-list-three-categories-real-60s', elapsedMs)
})

test('real-clock overview dashboard overview returns within five seconds without duplicate business reads', async ({ context, page }) => {
  const unexpected = await service(context), observed = observer(page)
  await page.goto('/admin-next/overview?project=' + project.projectId)
  await expect(page.locator('.board-kpis')).toContainText('12')
  await expect.poll(() => observed.count('initial', '/alerts?limit=20')).toBe(1)
  await page.waitForTimeout(100)
  observed.setPhase('A-B-A'); const start = Date.now()
  await navigate(page, 'dashboard'); await expect(page.getByRole('region', { name: '数据看板工作区' })).toBeVisible()
  await navigate(page, 'overview'); await expect(page.getByRole('region', { name: '总览工作区' })).toBeVisible()
  await expect(page.locator('.board-kpis')).toContainText('12')
  const elapsedMs = Date.now() - start
  expect(elapsedMs).toBeLessThan(5_000)
  for (const suffix of ['/dashboard/stats?range=today', '/streams', '/alerts?limit=20']) {
    expect(observed.count('initial', suffix)).toBe(1); expect(observed.count('A-B-A', suffix)).toBe(0)
  }
  expect(observed.count('A-B-A', '/auth/me')).toBe(0)
  expect(observed.count('A-B-A', '/auth/projects')).toBe(0)
  expect(unexpected).toEqual([])
  await observed.save('overview-dashboard-overview-real-clock', elapsedMs)
})

test('real-clock member list return reuses the bounded management snapshot', async ({ context, page }) => {
  const unexpected = await service(context), observed = observer(page)
  await page.goto('/admin-next/members?project=' + project.projectId)
  await expect(page.getByRole('heading', { name: '验收成员', exact: true })).toBeVisible()
  await page.waitForTimeout(100)
  observed.setPhase('A-B-A'); const start = Date.now()
  await navigate(page, 'overview'); await expect(page.locator('.board-kpis')).toContainText('12')
  await navigate(page, 'members'); await expect(page.getByRole('heading', { name: '验收成员', exact: true })).toBeVisible()
  const elapsedMs = Date.now() - start
  expect(elapsedMs).toBeLessThan(5_000)
  // M32-T31 closes the member-list gap recorded by the preserved T30 evidence.
  expect(observed.count('initial', '/members')).toBe(1)
  expect(observed.count('A-B-A', '/members')).toBe(0)
  expect(observed.count('A-B-A', '/platform/accounts')).toBe(0)
  expect(unexpected).toEqual([])
  await observed.save('member-list-return-budget-met', elapsedMs)
})
