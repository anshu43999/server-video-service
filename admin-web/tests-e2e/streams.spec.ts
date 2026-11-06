import { adminPath, selectElementOption, toggleElementSwitch } from './helpers/navigation'
import { fixtureUser, fixtureProjects, fixtureProject, unscopedPath } from './helpers/project-fixture'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

type FixtureStream = Record<string, any> & { stream_id: string }
const image = readFileSync(resolve(process.cwd(), 'tests-e2e/fixtures/evidence_helmet_violation.png'))
function fixtureStreams(): FixtureStream[] {
  return [
    { stream_id: 'gate-01', display_name: '北门摄像机', source_type: 'rtsp', source_url: 'rtsp://operator:do-not-expose@camera/live?token=private', enabled: true, runtime_available: true, yolo_enabled: true, overlay_enabled: true, confidence: .25, max_fps: 20, frames_received: 240, frames_processed: 200, received_fps: 20, processed_fps: 16, last_latency_ms: 24.3, active_subscribers: 1, detections_last: 1, publish_state: 'connected', model_id: 'helmet', model: { modelId: 'helmet', name: '安全帽识别' } },
    { stream_id: 'west-02', display_name: '西侧通道', source_type: 'rtsp', enabled: false, runtime_available: false, runtime_state: 'disabled', yolo_enabled: true, confidence: .3, max_fps: 10, model_id: 'helmet', model: { modelId: 'helmet' } },
  ]
}

async function fakeSocket(page: Page) {
  await page.addInitScript(() => {
    const all: any[] = []
    ;(window as any).__streamSockets = all
    class FakeSocket {
      onopen: ((event: Event) => void) | null = null
      onmessage: ((event: MessageEvent) => void) | null = null
      onclose: ((event: CloseEvent) => void) | null = null
      onerror = null
      closed = false
      constructor(public url: string) { if (url.includes('/streams/')) all.push(this); setTimeout(() => this.onopen?.(new Event('open')), 0) }
      close() { this.closed = true }
    }
    ;(window as any).WebSocket = FakeSocket
  })
}

async function mockService(context: BrowserContext, streams: FixtureStream[] = fixtureStreams()) {
  const writes: { method: string; path: string; body: any }[] = []
  await context.route('**/aiyoloapi/**', async route => {
    const path = unscopedPath(new URL(route.request().url()).pathname)
    const method = route.request().method()
    const respond = (value: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) })
    if (path.endsWith('/auth/status')) return respond({ setupRequired: false, authenticated: true, user: { username: 'visual-admin', role: 'admin' } })
    if (path.endsWith('/auth/me')) return respond(fixtureUser())
    if (path.endsWith('/auth/projects')) return respond(fixtureProjects())
    if (path === '/aiyoloapi') return respond(fixtureProject)
    if (path.endsWith('/models')) return respond({ models: [{ modelId: 'helmet', name: '安全帽识别', version: '1', serverBindable: true }, { modelId: 'person', name: '人员检测', version: '2', serverBindable: true }, { modelId: 'retired', name: '弃用模型', serverBindable: false }] })
    if (method === 'GET' && path.endsWith('/streams')) return respond(streams)
    if (method === 'POST' && path.endsWith('/streams')) {
      const body = route.request().postDataJSON()
      writes.push({ method, path, body })
      const created = { ...body, runtime_available: true, enabled: true, yolo_enabled: false }
      streams.push(created)
      return respond(created, 201)
    }
    const match = path.match(/\/streams\/([^/]+)(?:\/(.*))?$/)
    if (!match) return respond({}, 404)
    const id = decodeURIComponent(match[1]!)
    const stream = streams.find(item => item.stream_id === id)
    const endpoint = match[2]
    if (!stream) return respond({ detail: 'stream not found' }, 404)
    if (endpoint === 'preview') return route.fulfill({ contentType: 'image/jpeg', headers: { 'X-Preview-Mode': stream.yolo_enabled && stream.overlay_enabled ? 'yolo' : 'raw' }, body: image })
    if (endpoint === 'playback' || endpoint === 'mjpeg') return respond({ detail: { code: 'live_video_retired' } }, 410)
    const body = method === 'DELETE' ? null : route.request().postDataJSON()
    writes.push({ method, path, body })
    if (method === 'DELETE') { streams.splice(streams.indexOf(stream), 1); return route.fulfill({ status: 204 }) }
    if (endpoint === 'config') {
      Object.assign(stream, body)
      if ('enabled' in body) { stream.runtime_available = body.enabled; stream.runtime_state = body.enabled ? 'connected' : 'disabled' }
      return respond(stream)
    }
    if (endpoint === 'yolo') { stream.yolo_enabled = body.enabled; return respond(stream) }
    if (endpoint === 'model') { stream.model_id = body.model_id; stream.model = { modelId: body.model_id }; return respond({ model: stream.model, stream_id: id }) }
    return respond({}, 404)
  })
  return writes
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
}

test('desktop stream operations use real IDs, protect source credentials and reconnect media', async ({ context, page }) => {
  const writes = await mockService(context)
  await fakeSocket(page)
  const errors: string[] = []
  const retiredRequests: string[] = []
  page.on('request', request => { if (/\/(playback|mjpeg|detections)(\?|$)/.test(request.url())) retiredRequests.push(request.url()) })
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(adminPath('/streams'))
  await expect(page.locator('.stream-list-item')).toHaveCount(2)
  await expect(page.locator('.stream-list-copy strong').first()).toBeVisible()
  expect((await page.locator('.stream-list-copy').first().boundingBox())!.width).toBeGreaterThan(100)
  await expect(page.locator('.stream-preview img')).toBeVisible()
  await expect(page.locator('.streams-page')).not.toContainText('do-not-expose')
  expect(await page.locator('.streams-page').innerHTML()).not.toContain('token=private')
  await selectElementOption(page, '绑定服务端模型', '人员检测 · 2')
  await expect(page.getByText('服务端模型绑定已更新。')).toBeVisible()
  await page.locator('.stream-settings').getByLabel('显示名称').fill('北门巡检')
  await page.getByLabel('置信度阈值').fill('0.45')
  await page.getByLabel('最大处理帧率').fill('15')
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect(page.getByText('视频流设置已保存。')).toBeVisible()
  const firstPreview = await page.locator('.stream-preview img').getAttribute('src')
  await page.getByRole('main', { name: '选中视频流详情' }).getByRole('button', { name: '停用', exact: true }).click()
  await expect(page.locator('.stream-preview img')).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => (window as any).__streamSockets.every((socket: any) => socket.closed))).toBe(true)
  await page.getByRole('button', { name: '启用', exact: true }).click()
  await expect(page.locator('.stream-preview img')).toBeVisible()
  expect(await page.locator('.stream-preview img').getAttribute('src')).not.toBe(firstPreview)
  await expect(page.locator('.stream-detections')).toContainText('在告警中心新增记录并提示')
  expect(await page.evaluate(() => (window as any).__streamSockets.length)).toBe(0)
  await expect(page.getByRole('link', { name: '打开 WHEP 播放地址' })).toHaveCount(0)
  expect(retiredRequests).toEqual([])
  await noOverflow(page)
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: '../evidence/M34/M34-T03-streams-desktop.png', fullPage: true })
  expect(writes.some(write => write.path.endsWith('/gate-01/config') && write.body.confidence === .45)).toBe(true)
  await page.getByRole('button', { name: '删除流配置' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: '取消' }).click()
  expect(writes.filter(write => write.method === 'DELETE')).toHaveLength(0)
  await page.getByRole('button', { name: '删除流配置' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: '删除配置', exact: true }).click()
  await expect(page.locator('.stream-list-item')).toHaveCount(1)
  expect(errors).toEqual([])
})

test('narrow workflow creates a source without echoing it and releases subscriptions on navigation', async ({ context, page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const writes = await mockService(context)
  await fakeSocket(page)
  await page.goto(adminPath('/streams'))
  await expect(page.locator('.stream-preview img')).toBeVisible()
  await expect(page.locator('.stream-list-copy strong').first()).toBeVisible()
  expect((await page.locator('.stream-list-copy').first().boundingBox())!.width).toBeGreaterThan(100)
  await noOverflow(page)
  await page.screenshot({ path: '../evidence/M34/M34-T03-streams-narrow.png', fullPage: true })
  await page.getByRole('button', { name: '新增视频流' }).click()
  const createDialog = page.getByRole('dialog')
  await expect(createDialog).toBeVisible()
  await expect(createDialog.getByRole('heading', { name: '登记视频流配置' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(createDialog).toHaveCount(0)
  await page.getByRole('button', { name: '新增视频流' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByLabel('流 ID', { exact: true }).fill('new-03')
  await page.getByRole('dialog').locator('.stream-create-form').getByLabel('显示名称').fill('临时摄像机')
  await page.getByLabel('接入地址').fill('rtsp://operator:creation-secret@camera/live')
  await noOverflow(page)
  await page.getByRole('button', { name: '创建配置', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.stream-list-item')).toHaveCount(3)
  await expect(page.locator('.stream-detail-header h3')).toHaveText('临时摄像机')
  expect(writes.find(write => write.path.endsWith('/streams'))?.body.source_url).toContain('creation-secret')
  expect(await page.locator('.streams-page').innerHTML()).not.toContain('creation-secret')
  await page.getByRole('button', { name: '打开导航' }).click()
  await page.getByRole('navigation', { name: '管理后台主导航' }).getByRole('link', { name: '规则配置' }).click()
  await expect(page).toHaveURL(/\/rules\?project=fixture-project$/)
  await expect.poll(() => page.evaluate(() => (window as any).__streamSockets.every((socket: any) => socket.closed))).toBe(true)
  await expect(page.locator('.stream-preview img')).toHaveCount(0)
})

test('dashboard create link opens the new stream modal directly', async ({ context, page }) => {
  await mockService(context)
  await fakeSocket(page)
  await page.goto(adminPath('/streams?create=1'))
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('dialog').getByLabel('流 ID', { exact: true })).toBeVisible()
})

test('API failure and empty storage remain explicit', async ({ context, page }) => {
  await mockService(context, [])
  await fakeSocket(page)
  let attempts = 0
  await context.route('**/aiyoloapi/projects/fixture-project/streams', route => {
    attempts += 1
    return route.fulfill({ status: attempts === 1 ? 503 : 200, contentType: 'application/json', body: JSON.stringify(attempts === 1 ? { detail: 'storage unavailable' } : []) })
  })
  await page.goto(adminPath('/streams'))
  await expect(page.getByText('视频流不可用')).toBeVisible()
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.getByText('暂无视频流配置')).toBeVisible()
  await expect(page.locator('.stream-list-item')).toHaveCount(0)
})

test('failed YOLO and model changes retain server state and display the error', async ({ context, page }) => {
  await mockService(context)
  await fakeSocket(page)
  await context.route('**/aiyoloapi/projects/fixture-project/streams/*/yolo', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'yolo_unavailable' }) }))
  await context.route('**/aiyoloapi/projects/fixture-project/streams/*/model', route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'model_not_available', message: 'model unavailable' } }) }))
  await page.goto(adminPath('/streams'))
  await toggleElementSwitch(page, 'YOLO 检测')
  await expect(page.getByText('yolo_unavailable')).toBeVisible()
  await expect(page.getByLabel('YOLO 检测')).toBeChecked()
  await selectElementOption(page, '绑定服务端模型', '人员检测 · 2')
  await expect(page.getByText('model unavailable')).toBeVisible()
  await expect(page.locator('.stream-settings .ui-select')).toContainText('安全帽识别')
})

test('polling preserves unsaved settings, reuses media and stops on unmount', async ({ context, page }) => {
  const streams = fixtureStreams()
  await mockService(context, streams)
  await fakeSocket(page)
  let previewRequests = 0
  page.on('request', request => { if (request.url().includes('/preview?')) previewRequests += 1 })
  await page.goto(adminPath('/streams'))
  await expect(page.locator('.stream-preview img')).toBeVisible()
  await page.locator('.stream-settings').getByLabel('显示名称').fill('尚未保存的编辑')
  streams[0]!.frames_received = 999
  await expect(page.locator('.stream-live-metrics')).toContainText('999', { timeout: 10000 })
  await expect(page.locator('.stream-settings').getByLabel('显示名称')).toHaveValue('尚未保存的编辑')
  expect(previewRequests).toBeGreaterThan(1)
  expect(await page.evaluate(() => (window as any).__streamSockets.length)).toBe(0)
  await page.getByRole('navigation', { name: '管理后台主导航' }).getByRole('link', { name: '规则配置' }).click()
  await expect(page.locator('.stream-preview img')).toHaveCount(0)
  const count = previewRequests
  await page.waitForTimeout(600)
  expect(previewRequests).toBe(count)
})

test('switching streams cancels the old preview without restoring playback or sockets', async ({ context, page }) => {
  const streams = fixtureStreams()
  streams[1]!.enabled = true
  streams[1]!.runtime_available = true
  await mockService(context, streams)
  await fakeSocket(page)
  const previewRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/preview?')) previewRequests.push(request.url()) })
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  let attempt = 0
  await context.route('**/aiyoloapi/projects/fixture-project/streams/gate-01/preview?*', async route => {
    attempt++
    if (attempt === 1) return route.fulfill({ contentType: 'image/jpeg', body: image })
    await gate
    await route.fulfill({ contentType: 'image/jpeg', headers: { 'X-Preview-Mode': 'yolo' }, body: image }).catch(() => {})
  })
  await page.goto(adminPath('/streams'))
  await expect(page.locator('.stream-preview img')).toBeVisible()
  await expect.poll(() => attempt).toBeGreaterThan(1)
  await page.locator('.stream-list-item').filter({ hasText: '西侧通道' }).click()
  await expect(page.locator('.stream-detail-header h3')).toHaveText('西侧通道')
  await expect(page.locator('.stream-preview img')).toBeVisible()
  release?.()
  await expect(page.locator('.preview-overlay-label')).toHaveText('RAW STREAM')
  expect(await page.evaluate(() => (window as any).__streamSockets.length)).toBe(0)
  expect(previewRequests.at(-1)).toContain('/west-02/preview')
})

test('preview failure has a usable retry and a fresh connection URL', async ({ context, page }) => {
  await mockService(context)
  await fakeSocket(page)
  let attempt = 0
  let recover = false
  await context.route('**/aiyoloapi/projects/fixture-project/streams/gate-01/preview?*', route => {
    attempt += 1
    return !recover ? route.abort('failed') : route.fulfill({ contentType: 'image/jpeg', body: image })
  })
  await page.goto(adminPath('/streams'))
  await expect(page.getByText('现场预览不可用')).toBeVisible()
  recover = true
  await page.getByRole('button', { name: '重连现场预览' }).click()
  await expect(page.locator('.stream-preview img')).toBeVisible()
  expect(attempt).toBeGreaterThanOrEqual(2)
})

test('no source frame clears the picture and YOLO disabled still previews raw video', async ({ context, page }) => {
  const streams = fixtureStreams()
  streams[0]!.yolo_enabled = false
  await mockService(context, streams)
  let hasFrame = true
  await context.route('**/streams/gate-01/preview?*', route => hasFrame
    ? route.fulfill({ contentType: 'image/jpeg', headers: { 'X-Preview-Mode': 'raw' }, body: image })
    : route.fulfill({ status: 204 }))
  await page.goto(adminPath('/streams'))
  await expect(page.locator('.stream-preview img')).toBeVisible()
  await expect(page.locator('.preview-overlay-label')).toHaveText('RAW STREAM')
  await expect(page.locator('.stream-detections')).toContainText('仍可查看原始画面')
  hasFrame = false
  await expect(page.locator('.stream-preview img')).toHaveCount(0)
  await expect(page.locator('.preview-state')).toContainText('等待视频帧')
  hasFrame = true
  await expect(page.locator('.stream-preview img')).toBeVisible()
})
