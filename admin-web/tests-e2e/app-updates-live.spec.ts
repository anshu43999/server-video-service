import { expect, test, type Page } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

test.skip(!process.env.APP_UPDATE_LIVE_MANIFEST, 'Run with the isolated M42-T09 runner')
const data = process.env.APP_UPDATE_LIVE_MANIFEST ? JSON.parse(readFileSync(process.env.APP_UPDATE_LIVE_MANIFEST, 'utf8')) : {}
const prefix = '/aiyoloapi/admin/app-updates'
const result: Record<string, unknown> = { noApiInterception: true, releases: {} }

async function login(page: Page, name = 't09-admin-a') {
  await page.goto('/admin/login?redirect=/platform/app-updates')
  await page.getByLabel('账号', { exact: true }).fill(name)
  await page.getByLabel('密码', { exact: true }).fill('acceptance-only-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
}

async function openArtifact(page: Page, code: number) {
  await page.getByRole('button', { name: '安装包与来源', exact: true }).click()
  const row = page.locator('.update-row').filter({ has: page.getByText('CODE ' + code, { exact: true }) })
  await row.getByRole('button', { name: '安装包详情', exact: true }).click()
  return page.getByRole('dialog', { name: '安装包详情', exact: true })
}

test('real upload, external verification, release, stop and forward recovery', async ({ page }) => {
  const http: { method: string; path: string; status: number }[] = []
  page.on('response', r => { const path = new URL(r.url()).pathname; if (path.startsWith(prefix)) http.push({ method: r.request().method(), path, status: r.status() }) })
  await login(page)
  await expect(page.getByRole('heading', { name: '让每一次升级都有据可查' })).toBeVisible()
  await page.getByText('其他安装包操作', { exact: true }).click()

  // Real multipart upload -> durable job -> SDK verification -> real MinIO.
  await page.getByRole('button', { name: '上传 APK', exact: true }).click()
  let edit = page.getByRole('dialog', { name: '上传 APK 至自有存储', exact: true })
  await edit.getByLabel('APK 安装包').setInputFiles(data.apks['100'])
  await edit.getByLabel('操作原因').fill('T09 browser real MinIO upload')
  await edit.getByRole('button', { name: '提交核验', exact: true }).click()
  let detail = page.getByRole('dialog', { name: '安装包详情', exact: true })
  await expect(detail.getByRole('heading', { name: /CODE 100/ })).toBeVisible({ timeout: 60000 })
  await expect(detail.getByRole('button', { name: '创建版本草稿', exact: true })).toBeVisible({ timeout: 60000 })
  await expect(detail).toContainText('自有 MinIO')
  await detail.getByRole('button', { name: '新增外链来源', exact: true }).click()
  edit = page.getByRole('dialog', { name: '新增同包下载来源', exact: true })
  await edit.getByLabel('APK 直链').fill('https://apk.example.com/100.apk')
  await edit.getByLabel('允许的下载及重定向域名').fill('apk.example.com')
  await edit.getByLabel('操作原因').fill('T09 add external mirror')
  await edit.getByRole('button', { name: '提交核验', exact: true }).click()
  // A mirror registration returns its staging artifact; follow the verified target after completion.
  await expect(page.getByRole('dialog', { name: '安装包详情', exact: true })).toContainText('重复文件已复用已有工件', { timeout: 60000 })
  await page.getByRole('button', { name: '查看已核验工件', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '安装包详情', exact: true })).toContainText('第三方 HTTPS')
  await page.getByRole('button', { name: '关闭详情', exact: true }).click()

  for (const code of [101, 102]) {
    if (code === 101) {
      await page.getByRole('button', { name: '登记外链', exact: true }).click()
      edit = page.getByRole('dialog', { name: '登记第三方 APK', exact: true })
      await edit.getByLabel('APK 直链').fill('https://apk.example.com/redirect.apk')
      await edit.getByLabel('允许的下载及重定向域名').fill('apk.example.com')
    } else {
      await page.getByRole('button', { name: '上传 APK', exact: true }).click()
      edit = page.getByRole('dialog', { name: '上传 APK 至自有存储', exact: true })
      await edit.getByLabel('APK 安装包').setInputFiles(data.apks['102'])
    }
    await edit.getByLabel('操作原因').fill('T09 real package ' + code)
    await edit.getByRole('button', { name: '提交核验', exact: true }).click()
    detail = page.getByRole('dialog', { name: '安装包详情', exact: true })
    await expect(detail.getByRole('heading', { name: new RegExp('CODE ' + code) })).toBeVisible({ timeout: 60000 })
    await expect(detail.getByRole('button', { name: '创建版本草稿', exact: true })).toBeVisible({ timeout: 60000 })
    await page.getByRole('button', { name: '关闭详情', exact: true }).click()
  }

  for (const channel of ['minio', 'external']) {
    // Keep the MinIO recovery bound before registering the external revision.
    if (channel === 'external') {
      detail = await openArtifact(page, 102)
      await detail.getByRole('button', { name: '新增外链来源', exact: true }).click()
      edit = page.getByRole('dialog', { name: '新增同包下载来源', exact: true })
      await edit.getByLabel('APK 直链').fill('https://apk.example.com/102.apk')
      await edit.getByLabel('允许的下载及重定向域名').fill('apk.example.com')
      await edit.getByLabel('操作原因').fill('T09 recovery mirror')
      await edit.getByRole('button', { name: '提交核验', exact: true }).click()
      await expect(page.getByRole('dialog', { name: '安装包详情', exact: true })).toContainText('重复文件已复用已有工件', { timeout: 60000 })
      await page.getByRole('button', { name: '查看已核验工件', exact: true }).click()
      await page.getByRole('button', { name: '关闭详情', exact: true }).click()
    }
    const ids: Record<string, string> = {}
    for (const code of [100, 101, 102]) {
      detail = await openArtifact(page, code)
      await detail.getByRole('button', { name: '创建版本草稿', exact: true }).click()
      edit = page.getByRole('dialog', { name: '创建版本草稿', exact: true })
      await edit.getByLabel('发布范围').selectOption({ label: `t09-local / ${channel} · test` })
      await edit.getByLabel('更新说明').fill(`T09 ${channel} ${code}`)
      await edit.getByLabel('操作原因').fill('T09 create release')
      const response = page.waitForResponse(r => r.url().endsWith(prefix + '/releases') && r.request().method() === 'POST')
      await edit.getByRole('button', { name: '创建草稿', exact: true }).click()
      const release = (await (await response).json()).resourceId
      ids[String(code)] = release
      detail = page.getByRole('dialog', { name: '版本详情', exact: true })
      await expect(detail.getByRole('heading', { name: new RegExp('CODE ' + code) })).toBeVisible()
      if (code !== 102) {
        await detail.getByRole('button', { name: '配置并发布', exact: true }).click()
        edit = page.getByRole('dialog', { name: '发布版本', exact: true })
        const source = channel === 'minio' && code === 100 ? '自有 MinIO' : '第三方 HTTPS'
        const option = edit.getByLabel('下载来源').locator('option').filter({ hasText: source }).first()
        await edit.getByLabel('下载来源').selectOption(await option.getAttribute('value') || '')
        await edit.getByLabel('操作原因').fill('T09 publish real package')
        await edit.getByRole('button', { name: '确认发布', exact: true }).click()
        await expect(edit).not.toBeVisible()
        await expect(page.getByRole('dialog', { name: '版本详情', exact: true }).locator('.update-detail-header .update-state')).toHaveText('已发布')
      }
      await page.getByRole('button', { name: '关闭详情', exact: true }).click()
    }
    // First stop without recovery; then attach a ready 102 package.
    await page.getByRole('button', { name: '发布版本', exact: true }).click()
    const row = page.locator('.update-row').filter({ has: page.locator('.update-id').filter({ hasText: ids['101']! }) })
    await row.getByRole('button', { name: '版本详情', exact: true }).click()
    await page.getByRole('button', { name: '快速回退与恢复', exact: true }).click()
    let rollback = page.getByRole('dialog', { name: '快速回退与恢复', exact: true })
    await rollback.getByLabel('恢复推荐的稳定版本').selectOption(ids['100']!)
    await rollback.getByLabel('回退原因').fill('T09 stop problem package before recovery')
    await rollback.getByRole('button', { name: '预览影响', exact: true }).click()
    await expect(rollback).toContainText('预览通过')
    const apply = page.waitForResponse(r => r.url().endsWith(prefix + '/rollbacks') && r.request().method() === 'POST')
    await rollback.getByRole('button', { name: '确认执行回退', exact: true }).click()
    const applied = await apply
    const replay = await page.request.post(prefix + '/rollbacks', { data: applied.request().postDataJSON() })
    expect(replay.status()).toBe(202)
    expect((await replay.json()).operationId).toBe((await applied.json()).operationId)
    await expect(rollback).toContainText('设备恢复阶段：待恢复包就绪')
    await rollback.getByRole('button', { name: '关闭', exact: true }).click()
    await row.getByRole('button', { name: '版本详情', exact: true }).click()
    await page.getByRole('button', { name: '快速回退与恢复', exact: true }).click()
    rollback = page.getByRole('dialog', { name: '快速回退与恢复', exact: true })
    await rollback.getByLabel('恢复推荐的稳定版本').selectOption(ids['100']!)
    await rollback.getByLabel('更高版本码的恢复包').selectOption(ids['102']!)
    await rollback.getByLabel('回退原因').fill('T09 attach higher version recovery')
    await rollback.getByRole('button', { name: '预览影响', exact: true }).click()
    await expect(rollback).toContainText('恢复包已就绪')
    await rollback.getByRole('button', { name: '确认执行回退', exact: true }).click()
    await expect(rollback).toContainText('策略阶段：已生效')
    await expect(rollback).toContainText('恢复包已就绪，等待设备发现及用户安装')
    await page.screenshot({ path: join(data.evidence, `recovery-${channel}-1440.png`), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: join(data.evidence, `recovery-${channel}-390.png`), fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.setViewportSize({ width: 1440, height: 1000 })
    await rollback.getByRole('button', { name: '关闭', exact: true }).click()
    ;(result.releases as Record<string, unknown>)[channel] = ids
  }
  await page.getByRole('button', { name: '操作审计', exact: true }).click()
  await expect(page.locator('.update-audit-row').first()).toContainText('app_rollback')
  result.http = http
  writeFileSync(join(data.evidence, 'browser.json'), JSON.stringify(result, null, 2))
})

for (const account of ['t09-owner', 't09-user']) test(`real ${account} cannot enter platform release management`, async ({ page }) => {
  await login(page, account)
  await expect(page).toHaveURL(/\/projects/)
  await expect(page.getByRole('link', { name: 'App 版本管理', exact: true })).not.toBeVisible()
  const response = await page.request.post(prefix + '/external-artifacts', { data: {} })
  expect(response.status()).toBe(403)
})
