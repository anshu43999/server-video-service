import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'
import type { ConversionJob } from '../src/features/models/types'

const config = { mode: 'local', distribution: 'Ubuntu', python_path: 'python', input_size: 640, calibration_data: '', default_calibration_dataset_id: '', timeout_seconds: 1800, auto_convert: false, remote_endpoint: '', remote_token_env: 'TOKEN_ENV', remote_allow_insecure_http: false, remote_poll_interval_seconds: 2, remote_verifier_mode: 'local' }
const job = (overrides: Partial<ConversionJob> = {}): ConversionJob => ({ id: 'model-job', action: 'inspect', status: 'running', attempt: 1, created_at: 1, metadata: { name: '隔离任务' }, ...overrides })
const model = { modelId: 'fixture-model', name: '隔离模型', version: '1', status: 'DRAFT', serverBindable: false, artifacts: [] }
async function service(context: BrowserContext) {
  const state = { user: fixtureUser(), projects: [fixtureProject], models: [model], jobs: [job({ status: 'failed' })], meStatus: 200, projectsStatus: 200, meGate: undefined as Promise<void> | undefined, modelGate: undefined as Promise<void> | undefined, metricGate: undefined as Promise<void> | undefined, reads: [] as string[], writes: [] as string[] }
  await context.route('**/aiyoloapi/**', async route => {
    const path = new URL(route.request().url()).pathname
    ;(route.request().method() === 'GET' ? state.reads : state.writes).push(path)
    const reply = (json: unknown, status = 200) => route.fulfill({ json, status }).catch(() => {})
    if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: state.user })
    if (path.endsWith('/auth/me')) { await state.meGate; return reply(state.meStatus === 200 ? state.user : { detail: 'expired' }, state.meStatus) }
    if (path.endsWith('/auth/projects')) return reply({ contractVersion: 'm33-v1', projects: state.projects }, state.projectsStatus)
    if (path.endsWith('/conversion/jobs')) return reply({ jobs: state.jobs })
    if (path.endsWith('/conversion/config')) return reply({ config, max_upload_bytes: 1000, supported_modes: ['local'] })
    if (path.endsWith('/conversion/calibration-datasets')) return reply({ datasets: [], max_upload_bytes: 1000 })
    if (path.endsWith('/conversion/check')) return reply(job({ id: 'check', action: 'check', status: 'queued' }), 202)
    if (path.endsWith('/models')) { await state.modelGate; return reply({ models: state.models }) }
    if (path.endsWith('/auth/logout')) { state.meStatus = 401; return reply({ ok: true }) }
    if (path.endsWith('/metrics')) {
      if (path === '/aiyoloapi/metrics') return reply({ scope: 'platform', system: { cpu_percent: 0, memory_percent: 20, disk_percent: 30, gpu: null }, streams: { total: 1, framesReceived: 100, framesProcessed: 50, framesDropped: 50 } })
      if (path.includes('/projects/a/')) await state.metricGate
      return reply({ scope: 'project', projectId: path.split('/')[3], streams: { total: path.includes('/projects/a/') ? 111 : 222, framesReceived: 0, framesProcessed: 0, framesDropped: 0 } })
    }
    const project = state.projects.find(p => path === `/aiyoloapi/projects/${p.projectId}`)
    if (project) return reply(project)
    if (path.endsWith('/alerts')) return reply({ events: [] })
    return reply({ detail: 'isolated fixture: not found' }, 404)
  })
  await context.route('**/healthz', route => route.fulfill({ json: { status: 'ok', streams: 1, database: { configured: false, status: 'fallback' } } }))
  await context.routeWebSocket('**/aiyoloapi/**', socket => { socket.onMessage(() => {}) })
  return state
}
const count = (state: Awaited<ReturnType<typeof service>>, suffix: string) => state.reads.filter(path => path.endsWith(suffix)).length
async function observe(page: Page, state: Awaited<ReturnType<typeof service>>, name: string) {
  const counts = Object.fromEntries([...new Set(state.reads)].map(path => [path, state.reads.filter(p => p === path).length]))
  const timing = await page.evaluate(() => performance.getEntriesByType('resource').filter(e => new URL(e.name).pathname.startsWith('/aiyoloapi/')).map(e => { const r = e as PerformanceResourceTiming; return { path: new URL(r.name).pathname, startMs: r.startTime, durationMs: r.duration, transferBytes: r.transferSize, initiator: r.initiatorType } }))
  console.log(JSON.stringify({ scenario: name, counts }))
  await test.info().attach(name, { body: JSON.stringify({ environment: 'isolated Chromium, fixture APIs; not production latency', counts, timing }, null, 2), contentType: 'application/json' })
}

test('measure catalog -> upload -> calibration -> catalog without parent remount or extra identity requests', async ({ context, page }) => {
  const state = await service(context); await page.goto('/admin-next/models')
  await expect(page.locator('.model-card')).toHaveCount(1)
  await page.getByPlaceholder('搜索名称、ID、类别').fill('隔离')
  const initialMe = count(state, '/auth/me'), initialProjects = count(state, '/auth/projects')
  await page.getByRole('tab', { name: '上传与处理' }).click(); await expect(page.locator('.conversion-job')).toHaveCount(1)
  await page.getByRole('tab', { name: '校准集', exact: true }).click()
  await page.getByRole('tab', { name: '模型目录', exact: true }).click()
  await expect(page.getByPlaceholder('搜索名称、ID、类别')).toHaveValue('隔离')
  expect(count(state, '/auth/me')).toBe(initialMe); expect(count(state, '/auth/projects')).toBe(initialProjects)
  expect(count(state, '/models')).toBe(1)
  await observe(page, state, 'model-pane-navigation')
})

test('calibration deep link never loads a model catalog until needed', async ({ context, page }) => {
  const state = await service(context); await page.goto('/admin-next/models?pane=calibration')
  await expect(page.getByRole('heading', { name: '上传校准图片 ZIP' })).toBeVisible()
  expect(count(state, '/models')).toBe(0)
  await page.getByRole('tab', { name: '模型目录', exact: true }).click(); await expect(page.locator('.model-card')).toHaveCount(1)
  expect(count(state, '/models')).toBe(1)
})

test('initial history, progress and repeated terminal snapshots do not reload models', async ({ context, page }) => {
  const state = await service(context); state.jobs = [job(), job({ id: 'history', status: 'failed' })]
  await page.goto('/admin-next/models?pane=upload'); await expect(page.locator('.conversion-job')).toHaveCount(2)
  await expect.poll(() => count(state, '/models')).toBe(1)
  state.jobs[0] = job({ progress: 70, stage_label: '正在处理新进度' })
  await page.getByRole('button', { name: '刷新任务', exact: true }).click(); await expect(page.getByText('正在处理新进度', { exact: true })).toBeVisible()
  expect(count(state, '/models')).toBe(1)
  state.jobs[0] = job({ status: 'succeeded', result: { server_ready: true } })
  await page.getByRole('button', { name: '刷新任务', exact: true }).click(); await expect.poll(() => count(state, '/models')).toBe(2)
  await page.getByRole('button', { name: '刷新任务', exact: true }).click()
  await page.getByRole('tab', { name: '校准集', exact: true }).click()
  await page.getByRole('tab', { name: '上传与处理' }).click(); await expect(page.locator('.conversion-job')).toHaveCount(2)
  expect(count(state, '/models')).toBe(2)
  state.jobs[0] = job({ attempt: 2, status: 'failed' })
  await page.getByRole('button', { name: '刷新任务', exact: true }).click(); await expect.poll(() => count(state, '/models')).toBe(3)
  await observe(page, state, 'conversion-progress-terminal')
})

test('healthy focus verification keeps an open dialog visible and preserves component state', async ({ context, page }) => {
  const state = await service(context); await page.goto('/admin-next/models'); await expect(page.locator('.model-card')).toHaveCount(1)
  await page.getByRole('button', { name: '登记 Manifest', exact: true }).click()
  await page.getByLabel('Manifest 路径').fill('local-only-draft.json')
  let release!: () => void; state.meGate = new Promise(resolve => { release = resolve })
  const initialMe = count(state, '/auth/me')
  await page.evaluate(() => { window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('pageshow')) })
  await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'true')
  await expect(page.locator('#main-content')).not.toHaveAttribute('inert', '')
  await expect(page.getByRole('dialog')).toBeVisible()
  release(); state.meGate = undefined
  await expect(page.getByRole('dialog')).toBeVisible(); await expect(page.getByLabel('Manifest 路径')).toHaveValue('local-only-draft.json')
  expect(count(state, '/auth/me')).toBe(initialMe + 1); expect(count(state, '/models')).toBe(1)
  expect(state.writes).toEqual([])
})

test('permission revocation removes platform data and dialogs', async ({ context, page }) => {
  const state = await service(context); await page.goto('/admin-next/models'); await expect(page.locator('.model-card')).toHaveCount(1)
  await page.getByRole('button', { name: '登记 Manifest', exact: true }).click()
  state.user = fixtureUser('operator')
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.locator('.model-card')).toHaveCount(0); await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('alert')).toContainText('账号会话已变化')
})

test('failed verification and offline/online never restore sensitive pages automatically', async ({ context, page }) => {
  const state = await service(context); await page.goto('/admin-next/models'); await expect(page.locator('.model-card')).toHaveCount(1)
  state.projectsStatus = 503
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.locator('.model-card')).toHaveCount(0)
  await expect(page.getByRole('region', { name: '项目空间', exact: true }).getByRole('alert')).toBeVisible()
  state.projectsStatus = 200
  await page.getByRole('link', { name: '项目空间', exact: true }).click()
  await page.getByRole('link', { name: '模型资产', exact: true }).click(); await expect(page.locator('.model-card')).toHaveCount(1)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  await expect(page.locator('.model-card')).toHaveCount(0)
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(page.getByRole('button', { name: '进入 验收项目', exact: true })).toBeVisible()
  await expect(page.locator('.model-card')).toHaveCount(0)
})

test('aborts a pending model read on leaving and never displays the old response', async ({ context, page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))
  const state = await service(context)
  let release!: () => void; state.modelGate = new Promise(resolve => { release = resolve })
  const cancelled: string[] = []
  page.on('requestfailed', request => { if (new URL(request.url()).pathname === '/aiyoloapi/models') cancelled.push(request.failure()?.errorText ?? '') })
  await page.goto('/admin-next/models'); await expect.poll(() => count(state, '/models')).toBe(1)
  await page.getByRole('link', { name: '系统诊断', exact: true }).click()
  await expect(page).toHaveURL(new RegExp('/diagnostics$'))
  await expect(page.getByText('数据库：未配置数据库，开发内存回退', { exact: true })).toBeVisible()
  await expect(page.getByText('20.0%', { exact: true })).toBeVisible()
  await expect.poll(() => cancelled.length).toBe(1)
  release(); state.modelGate = undefined
  await expect(page.locator('.model-card')).toHaveCount(0)
  expect(cancelled[0]).toContain('ERR_ABORTED')
  expect(pageErrors).toEqual([])
})

test('real wall-clock 60-second idle window preserves 15-second checks and idle jobs budget', async ({ context, page }) => {
  test.setTimeout(90_000)
  const state = await service(context); await page.goto('/admin-next/models?pane=upload'); await expect(page.locator('.conversion-job')).toHaveCount(1)
  const before = { me: count(state, '/auth/me'), projects: count(state, '/auth/projects'), jobs: count(state, '/conversion/jobs'), models: count(state, '/models') }
  await page.waitForTimeout(60_500)
  const delta = { me: count(state, '/auth/me') - before.me, projects: count(state, '/auth/projects') - before.projects, jobs: count(state, '/conversion/jobs') - before.jobs, models: count(state, '/models') - before.models }
  expect(delta.me).toBe(4); expect(delta.projects).toBe(4); expect(delta.models).toBe(0)
  expect(delta.jobs).toBe(2)
  console.log(JSON.stringify({ scenario: 'real-60s-idle-delta', delta }))
  await observe(page, state, 'real-60s-idle')
})

test('rapid A/B switching cancels late A results without reviving old project data', async ({ context, page }) => {
  const state = await service(context)
  state.projects = ['a', 'b'].map(id => ({ ...fixtureProject, projectId: id, projectCode: id, displayName: `项目 ${id}` }))
  let release!: () => void; state.metricGate = new Promise(resolve => { release = resolve })
  await page.goto('/admin-next/project-diagnostics?project=a')
  await expect.poll(() => count(state, '/projects/a/metrics')).toBe(1)
  await page.evaluate(() => { window.history.pushState({}, '', '/admin-next/project-diagnostics?project=b'); window.dispatchEvent(new PopStateEvent('popstate')) })
  await expect(page.getByRole('region', { name: '当前项目上下文' })).toContainText('项目 b')
  await expect(page.locator('.model-readiness')).toContainText('222')
  release(); state.metricGate = undefined
  await expect(page.locator('.model-readiness')).not.toContainText('111')
  await expect(page.locator('.model-panel')).toContainText('b')
})

test('membership revision change clears the mounted project', async ({ context, page }) => {
  const state = await service(context); await page.goto(`/admin-next/project-diagnostics?project=${fixtureProject.projectId}`)
  await expect(page.getByRole('heading', { name: '当前项目运行汇总' })).toBeVisible()
  state.projects = [{ ...fixtureProject, revision: 2 }]
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.getByRole('heading', { name: '当前项目运行汇总' })).toHaveCount(0)
  await expect(page.getByRole('alert')).toContainText('项目状态或成员权限已变化')
})

test('cross-tab logout clears another platform tab and cancels its open dialog', async ({ context, page }) => {
  await service(context); await page.goto('/admin-next/models'); await expect(page.locator('.model-card')).toHaveCount(1)
  const other = await context.newPage(); await other.goto('/admin-next/models'); await expect(other.locator('.model-card')).toHaveCount(1)
  await other.getByRole('button', { name: '登记 Manifest', exact: true }).click()
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await other.bringToFront(); await other.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(other).toHaveURL(new RegExp('/login'))
  await expect(other.locator('.model-card')).toHaveCount(0); await expect(other.getByRole('dialog')).toHaveCount(0)
})

test('project to platform performs one pair and never re-enters old project', async ({ context, page }) => {
  const state = await service(context); await page.goto(`/admin-next/project-diagnostics?project=${fixtureProject.projectId}`)
  await expect(page.getByRole('region', { name: '当前项目上下文' })).toContainText('验收项目')
  const entryReads = count(state, `/projects/${fixtureProject.projectId}`), initialMe = count(state, '/auth/me'), initialProjects = count(state, '/auth/projects')
  await page.getByRole('link', { name: '模型资产', exact: true }).click(); await expect(page.locator('.model-card')).toHaveCount(1)
  expect(count(state, `/projects/${fixtureProject.projectId}`)).toBe(entryReads)
  expect(count(state, '/auth/me')).toBe(initialMe + 1); expect(count(state, '/auth/projects')).toBe(initialProjects + 1)
  await observe(page, state, 'project-to-platform')
})

test('60 seconds idle retains permission monitoring but no repeated catalog reads', async ({ context, page }) => {
  const state = await service(context); await page.clock.install(); await page.goto('/admin-next/models?pane=upload')
  await expect(page.locator('.conversion-job')).toHaveCount(1)
  const before = { me: count(state, '/auth/me'), projects: count(state, '/auth/projects'), models: count(state, '/models') }
  for (let i = 0; i < 4; i++) {
    await page.clock.runFor(15_000)
    await expect.poll(() => count(state, '/auth/projects')).toBe(before.projects + i + 1)
    await expect(page.locator('#main-content')).not.toHaveAttribute('inert', '')
  }
  expect(count(state, '/auth/me')).toBe(before.me + 4); expect(count(state, '/models')).toBe(before.models)
  await observe(page, state, '60s-simulated-idle')
})
