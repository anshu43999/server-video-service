import { expect, test, type BrowserContext } from '@playwright/test'
import { adminPath } from './helpers/navigation'
import { fixtureProject, fixtureUser } from './helpers/project-fixture'

const prefix = '/aiyoloapi/admin/app-updates'
const scope = { contractVersion: 'app-update/v1', publisherId: 'test', packageName: 'com.aiyolo.inspection', deploymentId: 'test', channel: 'stable' }
const createdAt = '2026-10-29T06:00:00Z'
const artifact = { resourceId: 'apk-2', resourceType: 'artifact', state: 'verified', revision: 1, details: {
  packageName: scope.packageName, publisherId: 'test', versionCode: 2, versionName: '1.1.0', sizeBytes: 12582912,
  sha256: 'a'.repeat(64), signerSha256: 'b'.repeat(64), minSdk: 27, abis: ['arm64-v8a'],
  serverContractRange: { min: 1, max: 1 }, dataSchemaVersion: 19, readableDataSchemaRange: { min: 18, max: 19 }, jobs: [], errorCode: null, verifiedAt: createdAt, createdAt } }
const sources = [{ resourceId: 'source-minio', resourceType: 'source', state: 'verified', revision: 1,
  details: { artifactId: 'apk-2', storageMode: 'internal', accessMode: 'presigned', allowedDownloadHosts: ['minio.example.com'], sha256: 'a'.repeat(64), sizeBytes: 12582912, availabilityState: 'available', createdAt } },
{ resourceId: 'source-cdn', resourceType: 'source', state: 'verified', revision: 2,
  details: { artifactId: 'apk-2', storageMode: 'external', accessMode: 'public', allowedDownloadHosts: ['cdn.example.com'], sha256: 'a'.repeat(64), sizeBytes: 12582912, availabilityState: 'available', createdAt } }]
const release = { resourceId: 'release-2', resourceType: 'release', state: 'draft', revision: 1,
  details: { ...scope, policyId: 'policy-a', artifactId: 'apk-2', importance: 'normal', releasePurpose: 'normal', notes: ['<img src=x onerror=alert(1)>', '这是很长的更新说明。'.repeat(150)], minSupportedVersionCode: 1, restrictedCapabilities: [], sourceBinding: null, publishedAt: null, stoppedAt: null, createdAt } }

async function identity(context: BrowserContext, role = 'admin') {
  await context.route('**/aiyoloapi/auth/status', r => r.fulfill({ json: { setupRequired: false, authenticated: true, user: { username: 'test-admin', role } } }))
  await context.route('**/aiyoloapi/auth/me', r => r.fulfill({ json: fixtureUser(role) }))
  await context.route('**/aiyoloapi/auth/projects', r => r.fulfill({ json: { contractVersion: 'm33-v1', projects: role === 'admin' ? [fixtureProject] : [] } }))
  await context.route('**/aiyoloapi/projects/' + fixtureProject.projectId, r => r.fulfill({ json: fixtureProject }))
}
async function backend(context: BrowserContext) {
  const current = structuredClone(release)
  const writes: { path: string; body: any }[] = []
  const state = { failList: false, empty: false, conflict: false, pending: false }
  let operation = { operationId: 'rollback-a', status: 'applied', effectivePolicyRevision: 8, recoveryState: 'pending', deviceCounts: { not_discovered: 1 }, lastContactBefore: createdAt, errorCode: null }
  await context.route('**' + prefix + '/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() === 'POST') {
      const body = request.postDataJSON(); writes.push({ path, body })
      if (state.conflict) return route.fulfill({ status: 409, json: { code: 'policy_revision_conflict', message: 'conflict' } })
      if (path.endsWith('/rollback-preview')) return route.fulfill({ json: { expectedPolicyRevision: current.revision, previewFingerprint: 'c'.repeat(64), expiresAt: new Date(Date.now() + 120000).toISOString(), ready: true, blockers: [], contactedDevices: 2, affectedDevices: 1, recoveryState: body.recoveryReleaseId ? 'ready' : 'pending' } })
      if (path.endsWith('/rollbacks')) { operation.recoveryState = body.recoveryReleaseId ? 'ready' : 'pending'; return route.fulfill({ status: 202, json: operation }) }
      if (path.endsWith('/external-artifacts')) { state.pending = true; return route.fulfill({ status: 202, json: { resourceId: 'apk-2', state: 'pending', revision: 1 } }) }
      if (path.endsWith('/releases')) { current.details.notes = body.notes; current.details.importance = body.importance; return route.fulfill({ status: 201, json: { resourceId: current.resourceId, state: 'draft', revision: 1 } }) }
      current.revision++
      if (path.endsWith('/publish')) { current.state = 'published'; current.details.minSupportedVersionCode = body.minSupportedVersionCode; current.details.restrictedCapabilities = body.restrictedCapabilities; current.details.sourceBinding = { releaseId: current.resourceId, artifactId: 'apk-2', sourceId: body.sourceId, sourceRevision: body.sourceRevision } as any }
      if (path.endsWith('/stop')) current.state = 'stopped'
      return route.fulfill({ json: { resourceId: current.resourceId, state: current.state, revision: current.revision } })
    }
    if (path.endsWith('/configuration')) return route.fulfill({ json: { scopes: [scope], gateCapabilities: ['online.inference'], maxApkBytes: 8589934592, uploadEnabled: true, externalEnabled: true } })
    if (path.endsWith('/rollbacks/rollback-a')) return route.fulfill({ json: operation })
    if (path.endsWith('/download-sources')) return route.fulfill({ json: { items: state.pending ? [] : sources, nextCursor: null } })
    if (path.endsWith('/artifacts/apk-2')) return route.fulfill({ json: state.pending ? { ...artifact, state: 'pending', details: { ...artifact.details, jobs: [{ jobId: 'job-a', kind: 'external', state: 'queued', errorCode: null, resolvedArtifactId: null, targetArtifactId: null, createdAt }] } } : artifact })
    if (path.endsWith('/releases/release-2')) return route.fulfill({ json: current })
    if (state.failList) return route.fulfill({ status: 503, json: { code: 'service_unavailable' } })
    const rollbackChoices = current.state === 'published' ? [{ ...current, resourceId: 'release-stable', details: { ...current.details, notes: ['历史稳定行为'], artifactId: 'apk-1' } }, { ...current, resourceId: 'release-recovery', state: 'draft', details: { ...current.details, notes: ['高版本恢复'], artifactId: 'apk-3' } }] : []
    return route.fulfill({ json: { items: state.empty ? [] : path.endsWith('/artifacts') ? [artifact] : path.endsWith('/audit') ? [{ resourceId: 'audit-a', resourceType: 'audit', revision: 1, state: 'verified', details: { actorId: 'admin', action: 'publish', resourceId: current.resourceId, reason: '验收发布', result: 'succeeded', beforeRevision: 1, afterRevision: 2, createdAt } }] : [current, ...rollbackChoices], nextCursor: null } })
  })
  return { current, writes, state }
}

for (const width of [1440, 390]) test(`release workflow and keyboard at ${width}px`, async ({ context, page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 }); await identity(context); const api = await backend(context)
  await page.goto(adminPath('/platform/app-updates'))
  await expect(page.getByRole('heading', { name: '让每一次升级都有据可查' })).toBeVisible()
  await page.getByRole('button', { name: '版本详情', exact: true }).click()
  let detail = page.getByRole('dialog', { name: '版本详情', exact: true })
  await expect(detail.getByText('<img src=x onerror=alert(1)>', { exact: true })).toBeVisible()
  expect(await detail.locator('.update-notes img').count()).toBe(0)
  await expect(detail).toContainText('自有 MinIO'); await expect(detail).toContainText('第三方 HTTPS')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../harness/evidence/M42/T11-regression-detail-' + width + '.png', fullPage: true, animations: 'disabled' })
  await detail.getByRole('button', { name: '配置并发布' }).click()
  const publish = page.getByRole('dialog', { name: '发布版本', exact: true })
  await publish.getByLabel('下载来源').selectOption('source-cdn')
  await publish.getByLabel('最低支持版本码').fill('2')
  await publish.getByLabel('online.inference', { exact: true }).check()
  await publish.getByLabel('操作原因').fill('兼容升级验收')
  await publish.getByRole('button', { name: '确认发布', exact: true }).focus(); await page.keyboard.press('Enter')
  await expect(publish).not.toBeVisible(); detail = page.getByRole('dialog', { name: '版本详情', exact: true })
  await expect(detail).toContainText('兼容门禁：低于 CODE 2')
  expect(api.writes[0]!.body).toMatchObject({ expectedPolicyRevision: 1, sourceId: 'source-cdn', sourceRevision: 2, minSupportedVersionCode: 2, restrictedCapabilities: ['online.inference'] })
  await detail.getByRole('button', { name: '停止分发', exact: true }).click()
  const stop = page.getByRole('dialog', { name: '停止分发', exact: true })
  await expect(stop).toContainText('不会卸载 App 或清除历史数据')
  await stop.getByLabel('操作原因').fill('停止问题版本')
  await stop.getByRole('button', { name: '确认停止分发', exact: true }).click()
  await expect(stop).not.toBeVisible(); await expect(page.getByRole('dialog', { name: '版本详情', exact: true })).toContainText('已停止')
  expect(api.writes[1]!.body.expectedPolicyRevision).toBe(2)
  await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).not.toBeVisible()
  await page.getByRole('button', { name: '操作审计', exact: true }).click(); await expect(page.locator('.update-audit-row')).toContainText('验收发布')
  await page.screenshot({ path: '../harness/evidence/M42/T11-regression-ledger-' + width + '.png', fullPage: true, animations: 'disabled' })
})

for (const width of [1440, 390]) test(`rollback preview, pending recovery and higher package at ${width}px`, async ({ context, page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 }); await identity(context)
  const api = await backend(context); api.current.state = 'published'
  await page.goto(adminPath('/platform/app-updates'))
  await page.getByRole('button', { name: '版本详情', exact: true }).first().click()
  await page.getByRole('button', { name: '快速回退与恢复', exact: true }).click()
  let dialog = page.getByRole('dialog', { name: '快速回退与恢复', exact: true })
  await dialog.getByLabel('恢复推荐的稳定版本').selectOption('release-stable')
  await dialog.getByLabel('回退原因').fill('问题版本止损')
  await expect(dialog.getByRole('button', { name: '确认执行回退', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: '预览影响', exact: true }).click()
  await expect(dialog).toContainText('当前问题版 1 台')
  await expect(dialog).toContainText('待恢复包就绪')
  await dialog.getByRole('button', { name: '确认执行回退', exact: true }).focus(); await page.keyboard.press('Enter')
  await expect(dialog).toContainText('策略阶段：已生效')
  await expect(dialog).toContainText('设备恢复阶段：待恢复包就绪')
  expect(api.writes[1]!.body).toMatchObject({ expectedPolicyRevision: 1, recoveryReleaseId: null, affectedReleaseIds: ['release-2'], stableReleaseId: 'release-stable', previewFingerprint: 'c'.repeat(64) })
  await dialog.getByRole('button', { name: '刷新恢复进度', exact: true }).click()
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '版本详情', exact: true }).first().click()
  await page.getByRole('button', { name: '快速回退与恢复', exact: true }).click()
  dialog = page.getByRole('dialog', { name: '快速回退与恢复', exact: true })
  await dialog.getByLabel('恢复推荐的稳定版本').selectOption('release-stable')
  await dialog.getByLabel('更高版本码的恢复包').selectOption('release-recovery')
  await dialog.getByLabel('回退原因').fill('恢复包已完成验证')
  await dialog.getByRole('button', { name: '预览影响', exact: true }).click()
  await expect(dialog).toContainText('恢复包已就绪')
  await dialog.getByLabel('回退原因').fill('恢复包二次确认')
  await expect(dialog.getByRole('button', { name: '确认执行回退', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: '预览影响', exact: true }).click()
  await dialog.getByRole('button', { name: '确认执行回退', exact: true }).click()
  await expect(dialog).toContainText('等待设备发现及用户安装')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../harness/evidence/M42/T11-regression-recovery-' + width + '.png', fullPage: true, animations: 'disabled' })
  await page.keyboard.press('Escape'); await expect(dialog).not.toBeVisible()
})

test('rollback blockers and stale preview require a fresh confirmation', async ({ context, page }) => {
  await identity(context); const api = await backend(context); api.current.state = 'published'
  await page.goto(adminPath('/platform/app-updates')); await page.getByRole('button', { name: '版本详情', exact: true }).first().click()
  await page.getByRole('button', { name: '快速回退与恢复', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '快速回退与恢复', exact: true })
  await dialog.getByLabel('恢复推荐的稳定版本').selectOption('release-stable')
  await dialog.getByLabel('回退原因').fill('验证证据不足')
  await context.route('**' + prefix + '/rollback-preview', r => r.fulfill({ json: { expectedPolicyRevision: 1, previewFingerprint: 'd'.repeat(64), expiresAt: new Date(Date.now() + 120000).toISOString(), ready: false, blockers: ['recovery_evidence_missing'], contactedDevices: 2, affectedDevices: 1, recoveryState: 'pending' } }))
  await dialog.getByRole('button', { name: '预览影响', exact: true }).click()
  await expect(dialog).toContainText('缺少绑定这些 APK 摘要的可信恢复验证证据')
  await expect(dialog.getByRole('button', { name: '确认执行回退', exact: true })).toBeDisabled()
  await context.unroute('**' + prefix + '/rollback-preview')
  await dialog.getByRole('button', { name: '预览影响', exact: true }).click()
  api.state.conflict = true
  await dialog.getByRole('button', { name: '确认执行回退', exact: true }).click()
  await expect(dialog).toContainText('策略已被其他操作修改')
  await expect(dialog.getByRole('button', { name: '确认执行回退', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
})

test('empty/error retry, external verification, draft and conflict recovery', async ({ context, page }) => {
  await identity(context); const api = await backend(context); api.state.empty = true
  await page.goto(adminPath('/platform/app-updates')); await expect(page.getByText('尚未发布 App 版本', { exact: true })).toBeVisible()
  api.state.failList = true; await page.getByRole('button', { name: '刷新台账' }).click(); await expect(page.getByText('版本台账暂不可用', { exact: true })).toBeVisible()
  api.state.failList = false; api.state.empty = false; await page.getByRole('button', { name: '重新加载' }).click()
  await page.getByText('其他安装包操作', { exact: true }).click()
  await page.getByRole('button', { name: '登记外链', exact: true }).click()
  const external = page.getByRole('dialog', { name: '登记第三方 APK', exact: true })
  await external.getByLabel('APK 直链').fill('https://cdn.example.com/app.apk')
  await external.getByLabel('允许的下载及重定向域名').fill('cdn.example.com')
  await external.getByLabel('操作原因').fill('外部托管')
  await external.getByRole('button', { name: '提交核验', exact: true }).click()
  let detail = page.getByRole('dialog', { name: '安装包详情', exact: true })
  await expect(detail).toContainText('第三方完整核验 · 排队中'); await expect(detail.getByRole('button', { name: '创建版本草稿' })).not.toBeVisible()
  await page.keyboard.press('Escape'); api.state.pending = false
  await page.getByRole('button', { name: '安装包详情', exact: true }).click()
  await detail.getByRole('button', { name: '创建版本草稿', exact: true }).click()
  const draft = page.getByRole('dialog', { name: '创建版本草稿', exact: true })
  await draft.getByLabel('提醒级别').selectOption('important'); await draft.getByLabel('更新说明').fill('重要更新\n修复问题')
  await draft.getByLabel('操作原因').fill('准备发布'); await draft.getByRole('button', { name: '创建草稿', exact: true }).click()
  detail = page.getByRole('dialog', { name: '版本详情', exact: true }); await expect(detail).toContainText('重要推荐')
  expect(api.writes[1]!.body.notes).toEqual(['重要更新', '修复问题'])
  await detail.getByRole('button', { name: '配置并发布', exact: true }).click(); api.state.conflict = true
  const publish = page.getByRole('dialog', { name: '发布版本', exact: true })
  await publish.getByLabel('操作原因').fill('并发发布'); await publish.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(publish).toContainText('策略已被其他操作修改'); await expect(publish.getByRole('button', { name: '确认发布', exact: true })).toBeDisabled()
  await publish.getByRole('button', { name: '关闭并重新确认', exact: true }).click(); await expect(detail).not.toBeVisible()
})

test('upload byte progress, pending registration and user cancellation', async ({ context, page }) => {
  await identity(context); await backend(context)
  // Deterministic browser transport events; real upload/MinIO integration is T03/T09.
  await page.addInitScript(() => {
    class UploadXHR {
      upload: any = {}; onabort?: () => void
      open() {} send() { setTimeout(() => this.upload.onprogress?.({ lengthComputable: true, loaded: 10, total: 10 }), 20) }
      abort() { this.onabort?.() }
    }
    window.XMLHttpRequest = UploadXHR as any
  })
  await page.goto(adminPath('/platform/app-updates')); await page.getByText('其他安装包操作', { exact: true }).click(); await page.getByRole('button', { name: '上传 APK', exact: true }).click()
  const upload = page.getByRole('dialog', { name: '上传 APK 至自有存储', exact: true })
  await upload.getByLabel('APK 安装包').setInputFiles({ name: 'release.apk', mimeType: 'application/vnd.android.package-archive', buffer: Buffer.from('test-only') })
  await upload.getByLabel('操作原因').fill('上传进度验收'); await upload.getByRole('button', { name: '提交核验', exact: true }).click()
  await expect(upload).toContainText('文件已发送，等待服务端登记')
  await page.keyboard.press('Escape'); await expect(upload).toBeVisible()
  await upload.getByRole('button', { name: '中断上传', exact: true }).click()
  await expect(upload).toContainText('上传已中断'); await expect(upload.getByRole('button', { name: '取消', exact: true })).toBeEnabled()
})

for (const role of ['operator', 'viewer']) test('denies App release route for ' + role, async ({ context, page }) => {
  await identity(context, role); let calls = 0
  await context.route('**' + prefix + '/**', r => { calls++; return r.fulfill({ status: 403 }) })
  await page.goto(adminPath('/platform/app-updates')); await expect(page).toHaveURL(/\/projects/)
  await expect(page.getByRole('link', { name: 'App 版本管理' })).not.toBeVisible(); expect(calls).toBe(0)
})

for (const width of [1440, 390]) test(`manual hosted release at ${width}px`, async ({ context, page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 }); await identity(context); const api = await backend(context)
  // The primary flow works with the service's MinIO upload disabled.
  await context.route('**' + prefix + '/configuration', r => r.fulfill({ json: { scopes: [scope], gateCapabilities: [], maxApkBytes: 8589934592, uploadEnabled: false, externalEnabled: true } }))
  await page.goto(adminPath('/platform/app-updates')); await page.getByRole('button', { name: '新建版本', exact: true }).click()
  const wizard = page.getByRole('dialog', { name: '新建 App 版本', exact: true })
  await expect(wizard.getByLabel('发布范围', { exact: true })).not.toBeVisible()
  await wizard.getByLabel('版本名称', { exact: true }).fill('1.1.0'); await wizard.getByLabel('版本码（versionCode）', { exact: true }).fill('3')
  await wizard.getByLabel('新版 APK 下载地址').fill('https://cdn.example.com/app.apk')
  await wizard.getByLabel('更新说明', { exact: true }).fill('新版说明\n<script>纯文本</script>')
  await wizard.getByLabel('操作原因', { exact: true }).fill('管理员手动托管'); await wizard.getByLabel('提醒级别').selectOption('important')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '../harness/evidence/M42/T11-form-' + width + '.png', fullPage: true, animations: 'disabled' })
  await wizard.getByRole('button', { name: '核验 APK', exact: true }).click()
  await expect(wizard).toContainText('已登记，等待完整 APK 核验')
  expect(api.writes).toHaveLength(1); expect(api.writes[0]!.body.allowedDownloadHosts).toEqual(['cdn.example.com'])
  api.state.pending = false; await wizard.getByRole('button', { name: '刷新核验状态', exact: true }).click()
  await expect(wizard).toContainText('填写的版本与 APK 不一致')
  await expect(wizard.getByRole('button', { name: '创建版本草稿', exact: true })).toBeDisabled()
  await wizard.getByLabel('版本码（versionCode）', { exact: true }).fill('2')
  await expect(wizard).toContainText('APK 核验通过'); expect(api.writes).toHaveLength(1)
  await page.screenshot({ path: '../harness/evidence/M42/T11-verified-' + width + '.png', fullPage: true, animations: 'disabled' })
  await wizard.getByRole('button', { name: '创建版本草稿', exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: '../harness/evidence/M42/T11-confirmation-' + width + '.png', fullPage: true, animations: 'disabled' })
  await wizard.getByRole('button', { name: '创建版本草稿', exact: true }).click()
  const detail = page.getByRole('dialog', { name: '版本详情', exact: true })
  await expect(detail).toContainText('重要推荐'); await expect(detail).toContainText('<script>纯文本</script>')
  expect(api.writes).toHaveLength(2); expect(api.writes[1]!.body).toMatchObject({ artifactId: 'apk-2', importance: 'important', notes: ['新版说明', '<script>纯文本</script>'] })
  expect(api.writes.some(w => w.path.endsWith('/publish'))).toBe(false)
})

test('manual release rejects HTTP and stops polling after close', async ({ context, page }) => {
  await identity(context); const api = await backend(context)
  let reads = 0
  page.on('request', r => { if (new URL(r.url()).pathname.endsWith('/artifacts/apk-2')) reads++ })
  await page.goto(adminPath('/platform/app-updates')); await page.getByRole('button', { name: '新建版本', exact: true }).click()
  const wizard = page.getByRole('dialog', { name: '新建 App 版本', exact: true })
  await wizard.getByLabel('版本名称', { exact: true }).fill('1.1.0'); await wizard.getByLabel('版本码（versionCode）', { exact: true }).fill('2')
  await wizard.getByLabel('新版 APK 下载地址').fill('http://cdn.example.com/app.apk'); await wizard.getByLabel('操作原因').fill('校验测试')
  await wizard.getByRole('button', { name: '核验 APK', exact: true }).click(); await expect(wizard.getByRole('alert')).toContainText('HTTPS')
  expect(api.writes).toHaveLength(0)
  await wizard.getByLabel('新版 APK 下载地址').fill('https://cdn.example.com/app.apk'); await wizard.getByRole('button', { name: '核验 APK', exact: true }).click()
  await expect(wizard).toContainText('等待完整 APK 核验'); await wizard.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(wizard).not.toBeVisible(); const count = reads
  await page.waitForTimeout(5400); expect(reads).toBe(count); expect(api.writes).toHaveLength(1)
})

test('manual release clears the wizard after server permission loss', async ({ context, page }) => {
  await identity(context); await backend(context)
  await context.route('**' + prefix + '/external-artifacts', r => r.fulfill({ status: 403, json: { code: 'platform_admin_required' } }))
  await page.goto(adminPath('/platform/app-updates')); await page.getByRole('button', { name: '新建版本', exact: true }).click()
  const wizard = page.getByRole('dialog', { name: '新建 App 版本', exact: true })
  await wizard.getByLabel('版本名称', { exact: true }).fill('1.1.0'); await wizard.getByLabel('版本码（versionCode）', { exact: true }).fill('2')
  await wizard.getByLabel('新版 APK 下载地址').fill('https://cdn.example.com/app.apk'); await wizard.getByLabel('操作原因').fill('权限失效')
  await wizard.getByRole('button', { name: '核验 APK', exact: true }).click()
  await expect(wizard).not.toBeVisible(); await expect(page.getByText('版本台账暂不可用', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '新建版本', exact: true })).toBeDisabled()
})
