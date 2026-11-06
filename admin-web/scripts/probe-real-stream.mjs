import { chromium, expect } from '@playwright/test'
import { randomBytes } from 'node:crypto'
import { writeFile } from 'node:fs/promises'

const origin = process.env.M32_PROBE_ORIGIN || 'http://127.0.0.1:18086'
const base = process.env.M32_PROBE_BASE || '/admin-next'
const task = process.env.M32_PROBE_TASK || 'M32-T06'
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
const api = context.request
const rows = async () => {
  const response = await api.get(`${origin}/aiyoloapi/streams`)
  expect(response.ok()).toBe(true)
  return response.json()
}
const report = { cycles: [], errors }
const reportPath = `../evidence/M32/${task}-real-rtsp.json`
async function checkpoint(stage) {
  report.stage = stage
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`)
  console.log(`[real-rtsp] ${stage}`)
}
try {
  const status = await api.get(`${origin}/aiyoloapi/auth/status`)
  expect((await status.json()).setupRequired).toBe(true)
  const setup = await api.post(`${origin}/aiyoloapi/auth/setup`, { data: { username: 'm32-probe', password: randomBytes(24).toString('hex') } })
  expect(setup.ok()).toBe(true)
  await page.goto(`${origin}${base}/streams`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '新增视频流' }).click()
  await page.getByLabel('流 ID', { exact: true }).fill('m32-real-probe')
  await page.locator('.stream-create-form').getByLabel('显示名称').fill('本机 RTSP 验收')
  await page.getByLabel('接入地址').fill('rtsp://127.0.0.1:18556/probe')
  await page.getByRole('button', { name: '创建配置', exact: true }).click()
  await expect.poll(async () => (await rows())[0]?.frames_received, { timeout: 30000 }).toBeGreaterThan(20)
  await expect.poll(() => page.locator('.stream-preview img').evaluate(image => image.naturalWidth), { timeout: 30000 }).toBeGreaterThan(0)
  report.image = await page.locator('.stream-preview img').evaluate(image => ({ width: image.naturalWidth, height: image.naturalHeight }))
  await checkpoint('first-frame')
  expect(await page.locator('.streams-page').innerHTML()).not.toContain('18556/probe')
  for (let cycle = 0; cycle < 3; cycle += 1) {
    const previous = await page.locator('.stream-preview img').getAttribute('src')
    await page.getByRole('main', { name: '选中视频流详情' }).getByRole('button', { name: '停用', exact: true }).click()
    await expect(page.locator('.stream-preview img')).toHaveCount(0)
    expect((await rows())[0].enabled).toBe(false)
    await page.getByRole('button', { name: '启用', exact: true }).click()
    await expect.poll(async () => (await rows())[0]?.frames_received, { timeout: 30000 }).toBeGreaterThan(20)
    await expect.poll(() => page.locator('.stream-preview img').evaluate(image => image.naturalWidth), { timeout: 30000 }).toBeGreaterThan(0)
    const next = await page.locator('.stream-preview img').getAttribute('src')
    expect(next).not.toBe(previous)
    report.cycles.push({ cycle: cycle + 1, frames: (await rows())[0].frames_received, freshPreview: next !== previous })
    await checkpoint(`restart-${cycle + 1}`)
  }
  await page.locator('.stream-settings').getByLabel('显示名称').fill('RTSP 参数验收')
  await page.getByLabel('置信度阈值').fill('0.41')
  await page.getByLabel('最大处理帧率').fill('12')
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect(page.getByText('视频流设置已保存。')).toBeVisible()
  report.settings = { confidence: (await rows())[0].confidence, max_fps: (await rows())[0].max_fps }
  expect(report.settings).toEqual({ confidence: .41, max_fps: 12 })
  await checkpoint('settings-saved')
  await page.locator('.stream-preview img').evaluate(async image => { await image.decode() })
  await page.evaluate(() => scrollTo(0, 0))
  await page.screenshot({ path: `../evidence/M32/${task}-real-rtsp-desktop.png`, fullPage: true })
  await page.getByRole('navigation', { name: '管理后台主导航' }).getByRole('link', { name: '规则配置' }).click()
  await expect(page.locator('.stream-preview img')).toHaveCount(0)
  await expect.poll(async () => (await rows())[0].active_subscribers).toBe(0)
  report.releasedSubscribers = true
  await checkpoint('subscriptions-released')
  await page.goto(`${origin}${base}/streams`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.stream-preview img')).toBeVisible()
  await page.getByRole('button', { name: '删除流配置' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: '删除配置', exact: true }).click()
  await expect(page.getByText('暂无视频流配置')).toBeVisible()
  expect(await rows()).toHaveLength(0)
  report.deletedTemporaryStream = true
  expect(errors).toEqual([])
  await checkpoint('complete')
  console.log(JSON.stringify(report))
} catch (error) {
  report.failure = error instanceof Error ? `${error.name}: ${error.message}` : String(error)
  await checkpoint('failed')
  throw error
} finally {
  await context.close()
  await browser.close()
}
