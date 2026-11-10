import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'
import { SESSION_EVENT_KEY } from '../src/api/sessionEvents'

const deferred = () => { let release!: () => void; const promise = new Promise<void>(resolve => { release = resolve }); return { promise, release } }
async function service(context: BrowserContext) {
  const state = { user: fixtureUser(), projects: [fixtureProject], meStatus: 200, projectsStatus: 200, modelsStatus: 200,
    meGate: undefined as Promise<void> | undefined, projectsGate: undefined as Promise<void> | undefined,
    reads: [] as string[], writes: [] as string[] }
  await context.route('**/aiyoloapi/**', async route => {
    const path = new URL(route.request().url()).pathname
    ;(route.request().method() === 'GET' ? state.reads : state.writes).push(path)
    const reply = (json: unknown, status = 200) => route.fulfill({ json, status }).catch(() => {})
    if (path.endsWith('/auth/status')) return reply({ authenticated: true, setupRequired: false, user: state.user })
    if (path.endsWith('/auth/me')) { await state.meGate; return reply(state.user, state.meStatus) }
    if (path.endsWith('/auth/projects')) { await state.projectsGate; return reply({ contractVersion: 'm33-v1', projects: state.projects }, state.projectsStatus) }
    if (path.endsWith('/models')) return reply({ models: Array.from({ length: 24 }, (_, i) => ({ modelId: `fixture-${i}`, name: `隔离模型 ${i}`, version: '1', status: 'DRAFT', serverBindable: false, artifacts: [] })) }, state.modelsStatus)
    if (path.endsWith('/alerts')) return reply({ events: [] })
    if (path === `/aiyoloapi/projects/${fixtureProject.projectId}`) return reply(fixtureProject)
    if (path.endsWith('/metrics')) return reply({ scope: 'project', projectId: fixtureProject.projectId, streams: { total: 1, framesReceived: 0, framesProcessed: 0, framesDropped: 0 } })
    return reply({ detail: 'isolated fixture: not found' }, 404)
  })
  await context.routeWebSocket('**/aiyoloapi/**', socket => { socket.onMessage(() => {}) })
  return state
}
const count = (state: Awaited<ReturnType<typeof service>>, suffix: string) => state.reads.filter(path => path.endsWith(suffix)).length
async function openDraft(page: Page) {
  await page.goto('/admin-next/models')
  await expect(page.locator('.model-card')).toHaveCount(24)
  await page.getByRole('button', { name: '登记 Manifest', exact: true }).click()
  await page.getByLabel('Manifest 路径').fill('local-only-draft.json')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.waitForTimeout(350) // finish the existing dialog animation before geometry sampling
}
async function beginSamples(page: Page) {
  await page.evaluate(() => {
    const main = document.querySelector<HTMLElement>('#main-content')!
    const card = document.querySelector('.model-card')!
    const dialog = document.querySelector<HTMLElement>('.el-dialog')!
    const input = dialog.querySelector<HTMLInputElement>('input')!
    input.focus(); input.setSelectionRange(3, 7)
    const sample = () => ({ mainVisible: getComputedStyle(main).visibility, dialogVisible: getComputedStyle(dialog).visibility,
      mainTop: main.getBoundingClientRect().top, dialogTop: dialog.getBoundingClientRect().top,
      scrollY, dialogScroll: dialog.parentElement!.scrollTop, focus: document.activeElement === input,
      selection: [input.selectionStart, input.selectionEnd], draft: input.value,
      sameNodes: document.querySelector('#main-content') === main && document.querySelector('.model-card') === card && document.querySelector('.el-dialog') === dialog,
      inert: main.inert, busy: main.getAttribute('aria-busy'), navigation: performance.getEntriesByType('navigation').length })
    const evidence = { baseline: sample(), samples: [] as ReturnType<typeof sample>[], running: true }
    Object.assign(window, { stabilityEvidence: evidence })
    const loop = () => { if (!evidence.running) return; evidence.samples.push(sample()); requestAnimationFrame(loop) }; loop()
  })
}
async function finishSamples(page: Page) {
  return page.evaluate(() => {
    const evidence = (window as unknown as { stabilityEvidence: { baseline: Record<string, unknown>; samples: Array<Record<string, unknown>>; running: boolean } }).stabilityEvidence
    evidence.running = false; return evidence
  })
}

for (const width of [1440, 390]) {
  test(`real 15-second verification keeps every sampled frame and draft stable at ${width}px`, async ({ context, page }) => {
    test.setTimeout(35_000)
    await page.setViewportSize({ width, height: 900 })
    const state = await service(context); await openDraft(page)
    const before = { me: count(state, '/auth/me'), projects: count(state, '/auth/projects'), models: count(state, '/models') }
    const gate = deferred(); state.meGate = gate.promise
    await beginSamples(page)
    await page.screenshot({ path: test.info().outputPath('before.png') })
    await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'true', { timeout: 20_000 })
    await page.waitForTimeout(800) // controlled slow response, not claimed as real service latency
    await page.screenshot({ path: test.info().outputPath('during.png') })
    gate.release(); state.meGate = undefined
    await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'false')
    const evidence = await finishSamples(page)
    await test.info().attach('frame-stability', { body: JSON.stringify({ ...evidence, delayMs: 800, environment: 'real Chromium, isolated synthetic APIs, real interval' }), contentType: 'application/json' })
    expect(evidence.samples.some(s => s.busy === 'true')).toBe(true)
    for (const sample of evidence.samples) {
      expect({ ...sample, busy: undefined }).toEqual({ ...evidence.baseline, busy: undefined })
      expect(sample.mainVisible).toBe('visible'); expect(sample.dialogVisible).toBe('visible'); expect(sample.focus).toBe(true); expect(sample.inert).toBe(false)
    }
    expect(count(state, '/auth/me') - before.me).toBe(1)
    expect(count(state, '/auth/projects') - before.projects).toBe(1)
    expect(count(state, '/models') - before.models).toBe(0)
    expect(state.writes).toEqual([])
  })
}

test('focus and pageshow preserve nonzero page scroll and the focused input', async ({ context, page }) => {
  const state = await service(context); await page.goto('/admin-next/models'); await expect(page.locator('.model-card')).toHaveCount(24)
  const snapshot = () => page.evaluate(() => ({ y: scrollY, top: document.querySelector('#main-content')!.getBoundingClientRect().top, focus: document.activeElement?.getAttribute('placeholder') }))
  await page.getByPlaceholder('搜索名称、ID、类别').fill('隔离')
  await page.evaluate(() => scrollTo(0, 450))
  const before = await snapshot(); expect(before.y).toBeGreaterThan(0)
  const gate = deferred(); state.meGate = gate.promise
  const me = count(state, '/auth/me')
  await page.evaluate(() => { window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('pageshow')) })
  await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'true')
  await page.waitForTimeout(800)
  expect(await snapshot()).toEqual(before)
  await expect(page.locator('#main-content')).toHaveCSS('visibility', 'visible')
  gate.release(); await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'false')
  expect(await snapshot()).toEqual(before); expect(count(state, '/auth/me')).toBe(me + 1); expect(count(state, '/models')).toBe(1)
})

for (const status of [401, 403, 404]) {
  test(`denial ${status} upgrades an in-flight routine check, masks teleport and restores unchanged context`, async ({ context, page }) => {
    const state = await service(context); await openDraft(page)
    const gate = deferred(); state.meGate = gate.promise
    const me = count(state, '/auth/me')
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'true')
    await expect(page.getByRole('dialog')).toBeVisible()
    const top = await page.locator('#main-content').evaluate(el => el.getBoundingClientRect().top)
    state.modelsStatus = status
    // Programmatic click reaches the real component/API client behind the modal;
    // not a raw fetch (which would bypass the app's denial handling).
    await page.getByRole('button', { name: '刷新目录', exact: true }).evaluate(el => (el as HTMLElement).click())
    await expect(page.locator('body')).toHaveClass(/permission-verifying/)
    await expect(page.getByRole('dialog')).not.toBeVisible()
    await expect(page.locator('#main-content')).toHaveAttribute('inert', '')
    expect(await page.locator('#main-content').evaluate(el => el.getBoundingClientRect().top)).toBe(top)
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await expect(page.locator('body')).toHaveClass(/permission-verifying/)
    gate.release(); state.meGate = undefined; state.modelsStatus = 200
    await expect(page.locator('body')).not.toHaveClass(/permission-verifying/)
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByLabel('Manifest 路径')).toHaveValue('local-only-draft.json')
    expect(count(state, '/auth/me')).toBe(me + 1); expect(state.writes).toEqual([])
  })
}

test('routine verification blocks a submitted write without replay or closing the draft', async ({ context, page }) => {
  const state = await service(context); await openDraft(page)
  const gate = deferred(); state.meGate = gate.promise
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'true')
  await page.getByRole('button', { name: '校验并登记', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('正在复核权限')
  expect(state.writes).toEqual([])
  gate.release(); await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'false')
  await expect(page.getByLabel('Manifest 路径')).toHaveValue('local-only-draft.json'); expect(state.writes).toEqual([])
})

for (const stage of ['me', 'projects'] as const) {
  test(`${stage} timeout clears visible old content and cannot be revived by a late response`, async ({ context, page }) => {
    const state = await service(context); await page.clock.install(); await openDraft(page)
    const gate = deferred(); state[stage === 'me' ? 'meGate' : 'projectsGate'] = gate.promise
    const before = count(state, stage === 'me' ? '/auth/me' : '/auth/projects')
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await expect.poll(() => count(state, stage === 'me' ? '/auth/me' : '/auth/projects')).toBe(before + 1)
    await page.clock.runFor(15_001)
    await expect(page.locator('.model-card')).toHaveCount(0); await expect(page.getByRole('dialog')).toHaveCount(0)
    gate.release(); await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'false')
    await expect(page.locator('.model-card')).toHaveCount(0); expect(state.writes).toEqual([])
  })
}

for (const signal of ['offline', 'cross-tab', 'bfcache', 'long-hidden']) {
  test(`${signal} invalidates a pending routine check and removes sensitive teleports`, async ({ context, page }) => {
    const state = await service(context); await page.clock.install(); await openDraft(page)
    const gate = deferred(); state.meGate = gate.promise
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'true')
    await page.evaluate(({ signal, key }) => {
      if (signal === 'cross-tab') window.dispatchEvent(new StorageEvent('storage', { key, newValue: 'synthetic-session-change' }))
      else if (signal === 'bfcache') window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))
      else if (signal === 'offline') window.dispatchEvent(new Event('offline'))
      else { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }); document.dispatchEvent(new Event('visibilitychange')) }
    }, { signal, key: SESSION_EVENT_KEY })
    if (signal === 'long-hidden') {
      gate.release(); state.meGate = undefined
      await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'false')
      await page.clock.runFor(5 * 60_000)
    }
    await expect(page.locator('.model-card')).toHaveCount(0); await expect(page.getByRole('dialog')).toHaveCount(0)
    gate.release(); state.meGate = undefined
    await expect(page.locator('#main-content')).toHaveAttribute('aria-busy', 'false')
    await expect(page.locator('body')).not.toHaveClass(/permission-verifying/)
    await expect(page.locator('.model-card')).toHaveCount(0)
  })
}
