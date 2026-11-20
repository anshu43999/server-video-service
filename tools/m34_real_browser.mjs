// Real existing built UI and real server only. Never fabricate API responses.
import { chromium, expect } from '../admin-web/node_modules/@playwright/test/index.mjs'
import fs from 'node:fs/promises'
import path from 'node:path'

const baseURL = process.env.M34_BASE_URL
const origin = new URL(baseURL)
if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port) throw new Error('loopback URL required')
const evidence = process.env.M34_EVIDENCE
const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  args: ['--disable-background-networking'],
})
const requests = [], responses = [], sockets = [], errors = [], blocked = []
const context = await browser.newContext({ baseURL, viewport: { width: 1440, height: 1000 } })
// Safety boundary: block external traffic, never substitute a mock response.
await context.route('**/*', route => {
  if (new URL(route.request().url()).origin === origin.origin) return route.continue()
  blocked.push(route.request().url())
  return route.abort('blockedbyclient')
})
const page = await context.newPage()
page.on('pageerror', e => errors.push(e.message))
page.on('request', r => requests.push({ method: r.method(), path: new URL(r.url()).pathname }))
page.on('response', r => { if (r.url().includes('/preview')) responses.push({ status: r.status(), mode: r.headers()['x-preview-mode'] }) })
page.on('websocket', socket => sockets.push(new URL(socket.url()).pathname))
let result = { scope: 'existing built PC UI against isolated real model/HTTP/PostgreSQL; NOT Android', passed: false }
try {
  await page.goto('/admin/projects')
  await page.getByLabel('账号', { exact: true }).fill('m34-owner-a')
  await page.getByLabel('密码', { exact: true }).fill(process.env.M34_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).not.toHaveURL(/login/)
  await page.goto('/admin/streams?project=' + process.env.M34_PROJECT)
  const frame = page.getByAltText('选中视频流的实时画面')
  await expect(frame).toBeVisible({ timeout: 20000 })
  await expect.poll(() => frame.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true)
  await expect(page.getByText('YOLO OVERLAY', { exact: true })).toBeVisible()
  await expect.poll(() => responses.some(r => r.status === 200 && r.mode === 'yolo')).toBe(true)
  result.modelNameDisplay = (await page.getByText('未命名模型', { exact: true }).count()) ? 'UNRESOLVED_DISPLAY_DEFECT' : 'no-unnamed-label-observed'
  await page.screenshot({ path: path.join(evidence, 'pc-yolo-preview.png'), fullPage: true })
  const streamPath = '/aiyoloapi/projects/' + process.env.M34_PROJECT + '/streams/real-input'
  expect((await context.request.post(streamPath + '/yolo', { data: { enabled: false } })).status()).toBe(200)
  await expect(page.getByText('RAW STREAM', { exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'pc-raw-preview.png'), fullPage: true })
  expect((await context.request.post(streamPath + '/yolo', { data: { enabled: true } })).status()).toBe(200)
  await expect(page.getByText('YOLO OVERLAY', { exact: true })).toBeVisible()
  await page.goto('/admin/projects')
  await page.waitForTimeout(500)
  const previewCount = requests.filter(r => r.path.endsWith('/preview')).length
  await page.waitForTimeout(2000)
  expect(requests.filter(r => r.path.endsWith('/preview')).length).toBe(previewCount)
  const retired = /\/(mjpeg|playback|whep|hls|detections)(\/|$)/i
  expect(requests.filter(r => retired.test(r.path))).toEqual([])
  expect(sockets.filter(p => retired.test(p) || /\/streams\/[^/]+\/ws$/.test(p))).toEqual([])
  expect(errors).toEqual([])
  result.passed = true
} catch (error) {
  result.error = String(error)
  await page.screenshot({ path: path.join(evidence, 'pc-failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  result = { ...result, requests, responses, sockets, errors, externalRequestsBlocked: blocked }
  await fs.writeFile(path.join(evidence, 'pc-browser.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify({ passed: result.passed, error: result.error, previewResponses: responses.length }))
  await browser.close()
}
