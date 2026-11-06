# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: app-updates-live.spec.ts >> real upload, external verification, release, stop and forward recovery
- Location: tests-e2e\app-updates-live.spec.ts:24:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: getByRole('dialog', { name: '快速回退与恢复', exact: true })
Expected substring: "策略阶段：已生效"
Received string:    "快速回退与恢复先预览影响，再原子提交策略停止问题版本并恢复稳定推荐。已安装问题版需要更高版本码的恢复包，始终由用户点击安装，不卸载或清除数据。问题版本（可多选）6cb879ae-95f2-4d79-8285-e3f731a6c92a · 已停止6482d8d7-7073-4811-a976-9b3d389822aa · 已发布恢复推荐的稳定版本请选择已发布的稳定版本6482d8d7-7073-4811-a976-9b3d389822aa · T09 minio 100更高版本码的恢复包尚无恢复包 · 先停止分发c9d41fa8-7536-4eb5-8760-f5e4542200be · T09 minio 102恢复包使用已核验且可用的最新来源修订；具体来源固定在预览指纹中。兼容验证证据由受控 CI 配置提供。回退原因预览影响预览通过已联系 0 台；当前问题版 0 台。未联系设备数量未知。设备恢复：恢复包已就绪；兼容门禁将清除。有效期至 2026/10/29 15:05:00查询历史恢复操作79f652be-9d9a-473e-a17f-9393de6a15bd操作 ID查询操作正在读取或提交，请稍候…关闭确认执行回退"
Timeout: 5000ms

Call log:
  - Expect "toContainText" getByRole('dialog', { name: '快速回退与恢复', exact: true }) with timeout 5000ms
  - waiting for getByRole('dialog', { name: '快速回退与恢复', exact: true })
    14 × locator resolved to <div role="dialog" aria-modal="true" aria-label="快速回退与恢复" class="el-overlay-dialog" aria-describedby="el-id-7091-15">…</div>
       - unexpected value "快速回退与恢复先预览影响，再原子提交策略停止问题版本并恢复稳定推荐。已安装问题版需要更高版本码的恢复包，始终由用户点击安装，不卸载或清除数据。问题版本（可多选）6cb879ae-95f2-4d79-8285-e3f731a6c92a · 已停止6482d8d7-7073-4811-a976-9b3d389822aa · 已发布恢复推荐的稳定版本请选择已发布的稳定版本6482d8d7-7073-4811-a976-9b3d389822aa · T09 minio 100更高版本码的恢复包尚无恢复包 · 先停止分发c9d41fa8-7536-4eb5-8760-f5e4542200be · T09 minio 102恢复包使用已核验且可用的最新来源修订；具体来源固定在预览指纹中。兼容验证证据由受控 CI 配置提供。回退原因预览影响预览通过已联系 0 台；当前问题版 0 台。未联系设备数量未知。设备恢复：恢复包已就绪；兼容门禁将清除。有效期至 2026/10/29 15:05:00查询历史恢复操作79f652be-9d9a-473e-a17f-9393de6a15bd操作 ID查询操作正在读取或提交，请稍候…关闭确认执行回退"

```

```yaml
- dialog "快速回退与恢复":
  - banner:
    - heading "快速回退与恢复" [level=2]
  - strong: 先预览影响，再原子提交策略
  - paragraph: 停止问题版本并恢复稳定推荐。已安装问题版需要更高版本码的恢复包，始终由用户点击安装，不卸载或清除数据。
  - group:
    - text: 问题版本（可多选）
    - checkbox "6cb879ae-95f2-4d79-8285-e3f731a6c92a · 已停止" [checked] [disabled]
    - text: 6cb879ae-95f2-4d79-8285-e3f731a6c92a · 已停止
    - checkbox "6482d8d7-7073-4811-a976-9b3d389822aa · 已发布" [disabled]
    - text: 6482d8d7-7073-4811-a976-9b3d389822aa · 已发布 恢复推荐的稳定版本
    - combobox "恢复推荐的稳定版本" [disabled]:
      - option "请选择已发布的稳定版本" [disabled]
      - option "6482d8d7-7073-4811-a976-9b3d389822aa · T09 minio 100" [disabled] [selected]
    - text: 更高版本码的恢复包
    - combobox "更高版本码的恢复包" [disabled]:
      - option "尚无恢复包 · 先停止分发" [disabled]
      - option "c9d41fa8-7536-4eb5-8760-f5e4542200be · T09 minio 102" [disabled] [selected]
    - paragraph: 恢复包使用已核验且可用的最新来源修订；具体来源固定在预览指纹中。兼容验证证据由受控 CI 配置提供。
    - text: 回退原因
    - textbox "回退原因" [disabled]: T09 attach higher version recovery
  - button "预览影响" [disabled]
  - region "回退影响预览":
    - heading "预览通过" [level=4]
    - paragraph: 已联系 0 台；当前问题版 0 台。未联系设备数量未知。
    - paragraph: 设备恢复：恢复包已就绪；兼容门禁将清除。
    - paragraph: 有效期至 2026/10/29 15:05:00
  - group: 查询历史恢复操作
  - status: 正在读取或提交，请稍候…
  - contentinfo:
    - button "关闭" [disabled]
    - button "确认执行回退" [disabled]
```

# Test source

```ts
  39  |   await expect(detail).toContainText('自有 MinIO')
  40  |   await detail.getByRole('button', { name: '新增外链来源', exact: true }).click()
  41  |   edit = page.getByRole('dialog', { name: '新增同包下载来源', exact: true })
  42  |   await edit.getByLabel('APK 直链').fill('https://apk.example.com/100.apk')
  43  |   await edit.getByLabel('允许的下载及重定向域名').fill('apk.example.com')
  44  |   await edit.getByLabel('操作原因').fill('T09 add external mirror')
  45  |   await edit.getByRole('button', { name: '提交核验', exact: true }).click()
  46  |   // A mirror registration returns its staging artifact; follow the verified target after completion.
  47  |   await expect(page.getByRole('dialog', { name: '安装包详情', exact: true })).toContainText('重复文件已复用已有工件', { timeout: 60000 })
  48  |   await page.getByRole('button', { name: '查看已核验工件', exact: true }).click()
  49  |   await expect(page.getByRole('dialog', { name: '安装包详情', exact: true })).toContainText('第三方 HTTPS')
  50  |   await page.getByRole('button', { name: '关闭详情', exact: true }).click()
  51  | 
  52  |   for (const code of [101, 102]) {
  53  |     if (code === 101) {
  54  |       await page.getByRole('button', { name: '登记外链', exact: true }).click()
  55  |       edit = page.getByRole('dialog', { name: '登记第三方 APK', exact: true })
  56  |       await edit.getByLabel('APK 直链').fill('https://apk.example.com/redirect.apk')
  57  |       await edit.getByLabel('允许的下载及重定向域名').fill('apk.example.com')
  58  |     } else {
  59  |       await page.getByRole('button', { name: '上传 APK', exact: true }).click()
  60  |       edit = page.getByRole('dialog', { name: '上传 APK 至自有存储', exact: true })
  61  |       await edit.getByLabel('APK 安装包').setInputFiles(data.apks['102'])
  62  |     }
  63  |     await edit.getByLabel('操作原因').fill('T09 real package ' + code)
  64  |     await edit.getByRole('button', { name: '提交核验', exact: true }).click()
  65  |     detail = page.getByRole('dialog', { name: '安装包详情', exact: true })
  66  |     await expect(detail.getByRole('heading', { name: new RegExp('CODE ' + code) })).toBeVisible({ timeout: 60000 })
  67  |     await expect(detail.getByRole('button', { name: '创建版本草稿', exact: true })).toBeVisible({ timeout: 60000 })
  68  |     await page.getByRole('button', { name: '关闭详情', exact: true }).click()
  69  |   }
  70  | 
  71  |   for (const channel of ['minio', 'external']) {
  72  |     // Keep the MinIO recovery bound before registering the external revision.
  73  |     if (channel === 'external') {
  74  |       detail = await openArtifact(page, 102)
  75  |       await detail.getByRole('button', { name: '新增外链来源', exact: true }).click()
  76  |       edit = page.getByRole('dialog', { name: '新增同包下载来源', exact: true })
  77  |       await edit.getByLabel('APK 直链').fill('https://apk.example.com/102.apk')
  78  |       await edit.getByLabel('允许的下载及重定向域名').fill('apk.example.com')
  79  |       await edit.getByLabel('操作原因').fill('T09 recovery mirror')
  80  |       await edit.getByRole('button', { name: '提交核验', exact: true }).click()
  81  |       await expect(page.getByRole('dialog', { name: '安装包详情', exact: true })).toContainText('重复文件已复用已有工件', { timeout: 60000 })
  82  |       await page.getByRole('button', { name: '查看已核验工件', exact: true }).click()
  83  |       await page.getByRole('button', { name: '关闭详情', exact: true }).click()
  84  |     }
  85  |     const ids: Record<string, string> = {}
  86  |     for (const code of [100, 101, 102]) {
  87  |       detail = await openArtifact(page, code)
  88  |       await detail.getByRole('button', { name: '创建版本草稿', exact: true }).click()
  89  |       edit = page.getByRole('dialog', { name: '创建版本草稿', exact: true })
  90  |       await edit.getByLabel('发布范围').selectOption({ label: `t09-local / ${channel} · test` })
  91  |       await edit.getByLabel('更新说明').fill(`T09 ${channel} ${code}`)
  92  |       await edit.getByLabel('操作原因').fill('T09 create release')
  93  |       const response = page.waitForResponse(r => r.url().endsWith(prefix + '/releases') && r.request().method() === 'POST')
  94  |       await edit.getByRole('button', { name: '创建草稿', exact: true }).click()
  95  |       const release = (await (await response).json()).resourceId
  96  |       ids[String(code)] = release
  97  |       detail = page.getByRole('dialog', { name: '版本详情', exact: true })
  98  |       await expect(detail.getByRole('heading', { name: new RegExp('CODE ' + code) })).toBeVisible()
  99  |       if (code !== 102) {
  100 |         await detail.getByRole('button', { name: '配置并发布', exact: true }).click()
  101 |         edit = page.getByRole('dialog', { name: '发布版本', exact: true })
  102 |         const source = channel === 'minio' && code === 100 ? '自有 MinIO' : '第三方 HTTPS'
  103 |         const option = edit.getByLabel('下载来源').locator('option').filter({ hasText: source }).first()
  104 |         await edit.getByLabel('下载来源').selectOption(await option.getAttribute('value') || '')
  105 |         await edit.getByLabel('操作原因').fill('T09 publish real package')
  106 |         await edit.getByRole('button', { name: '确认发布', exact: true }).click()
  107 |         await expect(edit).not.toBeVisible()
  108 |         await expect(page.getByRole('dialog', { name: '版本详情', exact: true }).locator('.update-detail-header .update-state')).toHaveText('已发布')
  109 |       }
  110 |       await page.getByRole('button', { name: '关闭详情', exact: true }).click()
  111 |     }
  112 |     // First stop without recovery; then attach a ready 102 package.
  113 |     await page.getByRole('button', { name: '发布版本', exact: true }).click()
  114 |     const row = page.locator('.update-row').filter({ has: page.locator('.update-id').filter({ hasText: ids['101']! }) })
  115 |     await row.getByRole('button', { name: '版本详情', exact: true }).click()
  116 |     await page.getByRole('button', { name: '快速回退与恢复', exact: true }).click()
  117 |     let rollback = page.getByRole('dialog', { name: '快速回退与恢复', exact: true })
  118 |     await rollback.getByLabel('恢复推荐的稳定版本').selectOption(ids['100']!)
  119 |     await rollback.getByLabel('回退原因').fill('T09 stop problem package before recovery')
  120 |     await rollback.getByRole('button', { name: '预览影响', exact: true }).click()
  121 |     await expect(rollback).toContainText('预览通过')
  122 |     const apply = page.waitForResponse(r => r.url().endsWith(prefix + '/rollbacks') && r.request().method() === 'POST')
  123 |     await rollback.getByRole('button', { name: '确认执行回退', exact: true }).click()
  124 |     const applied = await apply
  125 |     const replay = await page.request.post(prefix + '/rollbacks', { data: applied.request().postDataJSON() })
  126 |     expect(replay.status()).toBe(202)
  127 |     expect((await replay.json()).operationId).toBe((await applied.json()).operationId)
  128 |     await expect(rollback).toContainText('设备恢复阶段：待恢复包就绪')
  129 |     await rollback.getByRole('button', { name: '关闭', exact: true }).click()
  130 |     await row.getByRole('button', { name: '版本详情', exact: true }).click()
  131 |     await page.getByRole('button', { name: '快速回退与恢复', exact: true }).click()
  132 |     rollback = page.getByRole('dialog', { name: '快速回退与恢复', exact: true })
  133 |     await rollback.getByLabel('恢复推荐的稳定版本').selectOption(ids['100']!)
  134 |     await rollback.getByLabel('更高版本码的恢复包').selectOption(ids['102']!)
  135 |     await rollback.getByLabel('回退原因').fill('T09 attach higher version recovery')
  136 |     await rollback.getByRole('button', { name: '预览影响', exact: true }).click()
  137 |     await expect(rollback).toContainText('恢复包已就绪')
  138 |     await rollback.getByRole('button', { name: '确认执行回退', exact: true }).click()
> 139 |     await expect(rollback).toContainText('策略阶段：已生效')
      |                            ^ Error: expect(locator).toContainText(expected) failed
  140 |     await expect(rollback).toContainText('恢复包已就绪，等待设备发现及用户安装')
  141 |     await page.screenshot({ path: join(data.evidence, `recovery-${channel}-1440.png`), fullPage: true })
  142 |     await page.setViewportSize({ width: 390, height: 844 })
  143 |     await page.screenshot({ path: join(data.evidence, `recovery-${channel}-390.png`), fullPage: true })
  144 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  145 |     await page.setViewportSize({ width: 1440, height: 1000 })
  146 |     await rollback.getByRole('button', { name: '关闭', exact: true }).click()
  147 |     ;(result.releases as Record<string, unknown>)[channel] = ids
  148 |   }
  149 |   await page.getByRole('button', { name: '操作审计', exact: true }).click()
  150 |   await expect(page.locator('.update-audit-row').first()).toContainText('app_rollback')
  151 |   result.http = http
  152 |   writeFileSync(join(data.evidence, 'browser.json'), JSON.stringify(result, null, 2))
  153 | })
  154 | 
  155 | for (const account of ['t09-owner', 't09-user']) test(`real ${account} cannot enter platform release management`, async ({ page }) => {
  156 |   await login(page, account)
  157 |   await expect(page).toHaveURL(/\/projects/)
  158 |   await expect(page.getByRole('link', { name: 'App 版本管理', exact: true })).not.toBeVisible()
  159 |   const response = await page.request.post(prefix + '/external-artifacts', { data: {} })
  160 |   expect(response.status()).toBe(403)
  161 | })
  162 | 
```